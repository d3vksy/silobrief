from __future__ import annotations

import errno
import json
import os
import re
import secrets
import stat
import sys
import tempfile
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import BinaryIO, TypedDict, TypeVar, cast

from silobrief.index_version import INDEX_VERSION, is_rebuildable_index_version
from silobrief.language import (
    LanguageSettings,
    default_language_settings,
    parse_language_settings,
)
from silobrief.path_safety import has_link_like_component, is_link_like, is_link_like_stat

STATE_DIRECTORY = ".silobrief"
_BOUNDARY_ALIAS_PATTERN = re.compile(r"[a-z0-9-]{1,40}")
_NOTE_ID_PATTERN = re.compile(r"note-[0-9a-f]{64}")
_UNSAFE_SETUP_FILESYSTEM_MESSAGE = (
    "this filesystem cannot publish setup files safely; run sb from native Windows for a "
    "Windows-mounted project, or move the project to the WSL Linux filesystem"
)
_UNSAFE_SETUP_ERRNOS = {errno.EINVAL, errno.ENOSYS, errno.ENOTSUP, errno.EOPNOTSUPP}
DEFAULT_EXCLUDES = (
    ".git/",
    ".silobrief/",
    "__pycache__/",
    ".venv/",
    "venv/",
    "build/",
    "dist/",
)
_ResultT = TypeVar("_ResultT")


class SetupError(Exception):
    pass


class IndexStateError(SetupError):
    pass


class BoundaryData(TypedDict):
    alias: str
    description: str
    path: str


class ConfigData(TypedDict):
    boundaries: list[BoundaryData]
    default_excludes: list[str]
    schema_version: int


class HumanNoteData(TypedDict):
    comment: str
    id: str
    path: str


class NotesData(TypedDict):
    notes: list[HumanNoteData]
    notes_version: int


@dataclass(frozen=True, slots=True)
class _FileVersion:
    content: bytes
    identity: tuple[int, int]


@dataclass(frozen=True, slots=True)
class _FileSnapshot:
    version: _FileVersion
    access_time_ns: int
    modified_time_ns: int
    mode: int


def setup_project(project: Path) -> bool:
    root = _project_root(project)
    state = root / STATE_DIRECTORY

    with _protected_project_directory(root) as root_descriptor:
        existing_identity = _state_entry_exists(state, root_descriptor)
        if existing_identity is not None:
            return _initialize_or_validate_state(
                root,
                state,
                root_descriptor,
                existing_identity,
                existing=True,
            )

        try:
            _create_state_directory(state, root_descriptor)
        except FileExistsError:
            identity = _state_entry_identity(state, root_descriptor)
            return _initialize_or_validate_state(
                root,
                state,
                root_descriptor,
                identity,
                existing=True,
            )
        except OSError as error:
            raise SetupError(f"cannot create {STATE_DIRECTORY}: {error}") from error

        created_identity = _state_entry_identity(state, root_descriptor)
        return _initialize_or_validate_state(
            root,
            state,
            root_descriptor,
            created_identity,
            existing=False,
        )


def _initialize_or_validate_state(
    root: Path,
    state: Path,
    root_descriptor: int | None,
    identity: tuple[int, int],
    *,
    existing: bool,
) -> bool:
    initializing = not existing
    try:
        with _protected_state_directory(root, root_descriptor, expected_identity=identity) as (
            state_descriptor,
            _opened_identity,
        ):
            names = _state_entry_names(state, state_descriptor)
            if existing and {"config.json", "notes.json", "exports"} <= names:
                _validate_state(state, state_descriptor)
                return False
            initializing = True
            _validate_partial_state(state, state_descriptor, names)
            _complete_partial_state(state, state_descriptor)
            _validate_initialized_state(state, state_descriptor)
    except (OSError, SetupError) as error:
        if not initializing:
            raise
        raise SetupError(f"cannot initialize {STATE_DIRECTORY}: {error}") from error
    return True


def _complete_partial_state(
    state: Path,
    state_descriptor: int | None,
) -> None:
    try:
        _create_entry(state / "exports", "exports", state_descriptor)
    except FileExistsError:
        pass
    _validate_empty_exports(state, state_descriptor)
    for name, content in _default_state_files():
        _publish_default_file(state / name, content, state_descriptor)


def _state_entry_names(state: Path, state_descriptor: int | None) -> set[str]:
    try:
        entries = os.listdir(state if state_descriptor is None else state_descriptor)
    except OSError as error:
        raise SetupError(f"cannot inspect {STATE_DIRECTORY}: {error}") from error
    return set(entries)


def _default_state_files() -> tuple[tuple[str, bytes], ...]:
    return (
        (
            "config.json",
            _json_bytes(
                ConfigData(
                    boundaries=[],
                    default_excludes=list(DEFAULT_EXCLUDES),
                    schema_version=1,
                )
            ),
        ),
        ("language.json", _json_bytes(default_language_settings())),
        ("notes.json", _json_bytes(NotesData(notes=[], notes_version=1))),
    )


def _validate_partial_state(
    state: Path,
    state_descriptor: int | None,
    names: set[str],
) -> None:
    expected_files = dict(_default_state_files())
    unexpected = names - {*expected_files, "exports"}
    if unexpected:
        raise SetupError(
            f"incomplete {STATE_DIRECTORY} contains unexpected entries: "
            + ", ".join(sorted(unexpected))
        )
    if "exports" in names:
        _validate_empty_exports(state, state_descriptor)
    for name in names & expected_files.keys():
        _validate_default_file(state / name, name, state_descriptor, expected_files[name])


def _validate_initialized_state(state: Path, state_descriptor: int | None) -> None:
    names = _state_entry_names(state, state_descriptor)
    expected_files = dict(_default_state_files())
    if names != {*expected_files, "exports"}:
        raise SetupError(f"{STATE_DIRECTORY} changed during setup")
    _validate_empty_exports(state, state_descriptor)
    for name, content in expected_files.items():
        _validate_default_file(state / name, name, state_descriptor, content)


def _validate_empty_exports(state: Path, state_descriptor: int | None) -> None:
    path = state / "exports"
    try:
        expected = _entry_stat(path, "exports", state_descriptor)
    except OSError as error:
        raise SetupError(f"cannot inspect exports: {error}") from error
    if not stat.S_ISDIR(expected.st_mode) or is_link_like_stat(expected):
        raise SetupError("exports must remain a real directory")

    descriptor = -1
    try:
        if state_descriptor is None:
            descriptor = _open_windows_directory(path)
            opened = os.fstat(descriptor)
            if not _same_directory(expected, opened):
                raise SetupError("exports changed while being inspected")
            _validate_windows_directory_handle(descriptor, path, "exports")
            entries = os.listdir(path)
        else:
            descriptor = _open_posix_directory("exports", dir_fd=state_descriptor)
            opened = os.fstat(descriptor)
            if not _same_directory(expected, opened):
                raise SetupError("exports changed while being inspected")
            entries = os.listdir(descriptor)
        inspected = os.fstat(descriptor)
        current = _entry_stat(path, "exports", state_descriptor)
        if not _same_directory(opened, inspected) or not _same_directory(opened, current):
            raise SetupError("exports changed while being inspected")
    except OSError as error:
        raise SetupError(f"cannot inspect exports: {error}") from error
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    if entries:
        raise SetupError("exports must be empty while setup is incomplete")


def _validate_default_file(
    path: Path,
    name: str,
    state_descriptor: int | None,
    expected_content: bytes,
) -> None:
    try:
        metadata = _entry_stat(path, name, state_descriptor)
    except OSError as error:
        raise SetupError(f"cannot inspect {name}: {error}") from error
    identity = _regular_file_identity(metadata, name)
    if state_descriptor is not None and stat.S_IMODE(metadata.st_mode) != 0o600:
        raise SetupError(f"{name} permissions are not the setup default")
    target = _setup_entry_path(path, name, state_descriptor)
    try:
        with open(target, "rb") as stream:
            if _regular_file_identity(os.fstat(stream.fileno()), name) != identity:
                raise SetupError(f"{name} changed while being inspected")
            _verify_file_entry(path, name, state_descriptor, identity, name)
            content = stream.read()
            _verify_file_entry(path, name, state_descriptor, identity, name)
    except OSError as error:
        raise SetupError(f"cannot read {name}: {error}") from error
    if content != expected_content:
        raise SetupError(f"{name} content is not the setup default")


def _publish_default_file(
    path: Path,
    content: bytes,
    state_descriptor: int | None,
) -> None:
    try:
        _publish_setup_entry(path, content, state_descriptor)
    except FileExistsError:
        pass
    except OSError as error:
        raise SetupError(f"cannot create {path.name}: {error}") from error
    _validate_default_file(path, path.name, state_descriptor, content)


def _publish_setup_entry(
    path: Path,
    content: bytes,
    state_descriptor: int | None,
) -> None:
    with _owned_setup_temporary_file(path, state_descriptor) as (
        stream,
        temporary_name,
        temporary_identity,
    ):
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())
        if state_descriptor is None:
            _verify_temporary_entry(path, temporary_name, state_descriptor, temporary_identity)
        elif (
            _temporary_file_identity(stream.fileno(), path.name, expected_links=0)
            != temporary_identity
        ):
            raise SetupError(f"temporary file for {path.name} changed during setup")
        _publish_temporary_entry(
            path,
            temporary_name,
            state_descriptor,
            stream.fileno(),
        )


@contextmanager
def _owned_setup_temporary_file(
    path: Path,
    state_descriptor: int | None,
) -> Iterator[tuple[BinaryIO, str, tuple[int, int]]]:
    if state_descriptor is None:
        with tempfile.NamedTemporaryFile(
            mode="w+b",
            dir=path.parent,
            prefix=f".{path.name}-",
            suffix=".tmp",
            delete=True,
        ) as temporary:
            stream = cast(BinaryIO, temporary)
            temporary_name = str(stream.name)
            identity = _temporary_file_identity(stream.fileno(), path.name)
            _verify_temporary_entry(path, temporary_name, state_descriptor, identity)
            yield stream, temporary_name, identity
        return

    temporary_flag = getattr(os, "O_TMPFILE", 0)
    if not temporary_flag:
        raise SetupError(_UNSAFE_SETUP_FILESYSTEM_MESSAGE)

    def open_anonymous(_name: str, _flags: int) -> int:
        return os.open(
            ".",
            os.O_RDWR | temporary_flag,
            0o600,
            dir_fd=state_descriptor,
        )

    try:
        opened = open(path, "w+b", opener=open_anonymous)
    except OSError as error:
        if error.errno in _UNSAFE_SETUP_ERRNOS:
            raise SetupError(_UNSAFE_SETUP_FILESYSTEM_MESSAGE) from error
        raise
    with opened as stream:
        os.chmod(stream.fileno(), 0o600)
        identity = _temporary_file_identity(stream.fileno(), path.name, expected_links=0)
        yield stream, "", identity


def _setup_entry_path(path: Path, name: str, state_descriptor: int | None) -> Path:
    if state_descriptor is None:
        return path.parent / name
    return Path("/proc/self/fd") / str(state_descriptor) / name


def _publish_temporary_entry(
    path: Path,
    temporary_name: str,
    state_descriptor: int | None,
    source_descriptor: int,
) -> None:
    if state_descriptor is None:
        os.link(path.parent / temporary_name, path)
    else:
        _link_posix_no_replace(source_descriptor, path.name, state_descriptor)


def _link_posix_no_replace(
    source_descriptor: int,
    destination: str,
    state_descriptor: int,
) -> None:
    import ctypes

    library = ctypes.CDLL(None, use_errno=True)
    link = getattr(library, "linkat", None)
    if link is None:
        raise SetupError(_UNSAFE_SETUP_FILESYSTEM_MESSAGE)
    link.argtypes = (
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
    )
    link.restype = ctypes.c_int
    source = os.fsencode(f"/proc/self/fd/{source_descriptor}")
    if link(-100, source, state_descriptor, os.fsencode(destination), 0x400) != 0:
        error_number = ctypes.get_errno()
        if error_number in _UNSAFE_SETUP_ERRNOS:
            raise SetupError(_UNSAFE_SETUP_FILESYSTEM_MESSAGE)
        raise OSError(error_number, os.strerror(error_number), destination)


def _project_root(project: Path) -> Path:
    if has_link_like_component(project):
        raise SetupError("project root must not contain a symbolic link or reparse point")
    if not project.is_dir():
        raise SetupError("project root must be an existing directory")

    try:
        return project.resolve(strict=True)
    except OSError as error:
        raise SetupError(f"cannot resolve project root: {error}") from error


def find_project_root(start: Path) -> Path:
    if has_link_like_component(start):
        raise SetupError("current directory must not contain a symbolic link or reparse point")
    if not start.is_dir():
        raise SetupError("command must run from an existing directory")
    try:
        current = start.resolve(strict=True)
    except OSError as error:
        raise SetupError(f"cannot resolve current directory: {error}") from error

    for candidate in (current, *current.parents):
        state = candidate / STATE_DIRECTORY
        if state.exists() or is_link_like(state):
            _validate_state(state)
            return candidate
    raise SetupError(f"cannot find {STATE_DIRECTORY}; run sb setup first")


def load_config(root: Path) -> ConfigData:
    return _validate_state(root / STATE_DIRECTORY)


def save_config(root: Path, config: ConfigData) -> None:
    _write_json_atomic(root / STATE_DIRECTORY / "config.json", config)


def load_notes(root: Path) -> NotesData:
    return _parse_notes(_read_object(root / STATE_DIRECTORY / "notes.json"))


def save_notes(root: Path, notes: NotesData) -> None:
    _write_json_atomic(root / STATE_DIRECTORY / "notes.json", notes)


def load_language_settings(root: Path) -> LanguageSettings:
    path = root / STATE_DIRECTORY / "language.json"
    if not path.exists() and not is_link_like(path):
        return default_language_settings()
    try:
        return parse_language_settings(_read_object(path))
    except ValueError as error:
        raise SetupError(str(error)) from error


def save_language_settings(root: Path, settings: LanguageSettings) -> None:
    try:
        validated = parse_language_settings(dict(settings))
    except ValueError as error:
        raise SetupError(str(error)) from error
    _write_json_atomic(root / STATE_DIRECTORY / "language.json", validated)


def save_index(root: Path, content: bytes) -> None:
    _write_bytes_atomic(root / STATE_DIRECTORY / "index.json", content)


def mark_index_stale(root: Path) -> None:
    index = root / STATE_DIRECTORY / "index.json"
    if not index.exists() and not is_link_like(index):
        return
    data = _read_object(index)
    if data.get("stale") is True:
        return
    data["stale"] = True
    _write_json_atomic(index, data)


def update_config_with_stale_index(
    root: Path,
    updater: Callable[[ConfigData], tuple[ConfigData | None, _ResultT]],
    *,
    lock: Callable[[Path, int | None], AbstractContextManager[None]],
) -> _ResultT:
    """Apply one locked config update without leaving the loaded state directory."""
    state = root / STATE_DIRECTORY
    with _protected_project_directory(root) as root_descriptor:
        with _protected_state_directory(root, root_descriptor) as (
            state_descriptor,
            state_identity,
        ):
            with lock(state, state_descriptor):
                _verify_state_identity(state, root_descriptor, state_identity)
                config, config_snapshot = _load_config_for_update(state, state_descriptor)
                updated, result = updater(config)
                if updated is not None and updated != config:
                    validated = _parse_config(dict(updated))
                    _commit_config_update(
                        state,
                        state_descriptor,
                        config_snapshot,
                        validated,
                    )
                _verify_state_identity(state, root_descriptor, state_identity)
                return result


def _verify_state_identity(
    state: Path,
    root_descriptor: int | None,
    expected_identity: tuple[int, int],
) -> None:
    if _state_entry_identity(state, root_descriptor) != expected_identity:
        raise SetupError(f"{STATE_DIRECTORY} changed during config update")


def _load_config_for_update(
    state: Path,
    state_descriptor: int | None,
) -> tuple[ConfigData, _FileSnapshot]:
    snapshot = _read_file_snapshot(state / "config.json", state_descriptor, "config.json")
    config = _parse_config(_decode_object("config.json", snapshot.version.content))
    _validate_state(state, state_descriptor, config=config)
    return config, snapshot


def _commit_config_update(
    state: Path,
    state_descriptor: int | None,
    expected_config: _FileSnapshot,
    config: ConfigData,
) -> None:
    config_path = state / "config.json"
    _verify_file_version(
        config_path,
        "config.json",
        state_descriptor,
        expected_config.version,
        "config.json",
    )
    stale_write: tuple[_FileSnapshot, _FileVersion] | None = None
    try:
        stale_write = _mark_index_stale_in_state(state, state_descriptor)
        _write_bytes_in_state(
            config_path,
            _json_bytes(config),
            state_descriptor,
            expected_current=expected_config.version,
        )
    except BaseException:
        if stale_write is not None and _file_version_matches(
            config_path,
            "config.json",
            state_descriptor,
            expected_config.version,
        ):
            _restore_file_snapshot(
                state / "index.json",
                "index.json",
                state_descriptor,
                stale_write[0],
                stale_write[1],
            )
        raise


def _mark_index_stale_in_state(
    state: Path,
    state_descriptor: int | None,
) -> tuple[_FileSnapshot, _FileVersion] | None:
    path = state / "index.json"
    if not _entry_exists(path, "index.json", state_descriptor):
        return None
    snapshot = _read_file_snapshot(path, state_descriptor, "index.json")
    data = _decode_object("index.json", snapshot.version.content)
    if data.get("stale") is True:
        return None
    data["stale"] = True
    content = _json_bytes(data)
    identity = _write_bytes_in_state(
        path,
        content,
        state_descriptor,
        expected_current=snapshot.version,
    )
    return snapshot, _FileVersion(content=content, identity=identity)


def is_valid_boundary_alias(alias: str) -> bool:
    return _BOUNDARY_ALIAS_PATTERN.fullmatch(alias) is not None


def _write_json_atomic(
    path: Path,
    value: ConfigData | NotesData | LanguageSettings | dict[str, object],
) -> None:
    content = _json_bytes(value)
    _write_bytes_atomic(path, content)


def _write_json_in_state(
    path: Path,
    value: ConfigData | NotesData | LanguageSettings | dict[str, object],
    state_descriptor: int | None,
) -> None:
    _write_bytes_in_state(path, _json_bytes(value), state_descriptor)


def _json_bytes(
    value: ConfigData | NotesData | LanguageSettings | dict[str, object],
) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _write_bytes_atomic(path: Path, content: bytes) -> None:
    root = path.parent.parent
    with _protected_project_directory(root) as root_descriptor:
        with _protected_state_directory(root, root_descriptor) as (
            state_descriptor,
            _identity,
        ):
            _write_bytes_in_state(path, content, state_descriptor)


def _write_bytes_in_state(
    path: Path,
    content: bytes,
    state_descriptor: int | None,
    *,
    expected_current: _FileVersion | None = None,
) -> tuple[int, int]:
    try:
        descriptor, temporary_name = _create_temporary_file(path, state_descriptor)
    except OSError as error:
        raise SetupError(f"cannot create temporary file for {path.name}: {error}") from error
    temporary_identity: tuple[int, int] | None = None
    try:
        temporary_identity = _temporary_file_identity(descriptor, path.name)
        _verify_temporary_entry(path, temporary_name, state_descriptor, temporary_identity)
        stream = os.fdopen(descriptor, "wb")
        descriptor = -1
        with stream:
            stream.write(content)
        _verify_temporary_entry(path, temporary_name, state_descriptor, temporary_identity)
        if expected_current is not None:
            _verify_file_version(
                path,
                path.name,
                state_descriptor,
                expected_current,
                path.name,
            )
        _replace_temporary_entry(path, temporary_name, state_descriptor)
        _verify_file_content(
            path,
            path.name,
            state_descriptor,
            temporary_identity,
            f"update for {path.name}",
            content,
        )
        return temporary_identity
    except SetupError:
        raise
    except OSError as error:
        raise SetupError(f"cannot update {path.name}: {error}") from error
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        _discard_temporary_entry(path, temporary_name, state_descriptor, temporary_identity)


def _create_temporary_file(path: Path, state_descriptor: int | None) -> tuple[int, str]:
    if state_descriptor is None:
        return tempfile.mkstemp(
            dir=path.parent,
            prefix=f".{path.name}-",
            suffix=".tmp",
        )

    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | int(getattr(os, "O_NOFOLLOW", 0))
    for _attempt in range(100):
        name = f".{path.name}-{secrets.token_hex(8)}.tmp"
        try:
            return os.open(name, flags, 0o600, dir_fd=state_descriptor), name
        except FileExistsError:
            continue
    raise FileExistsError(f"cannot allocate a temporary name for {path.name}")


def _temporary_file_identity(
    descriptor: int,
    target_name: str,
    *,
    expected_links: int = 1,
) -> tuple[int, int]:
    try:
        metadata = os.fstat(descriptor)
    except OSError as error:
        raise SetupError(f"cannot inspect temporary file for {target_name}: {error}") from error
    if (
        not stat.S_ISREG(metadata.st_mode)
        or is_link_like_stat(metadata)
        or int(metadata.st_nlink) != expected_links
    ):
        raise SetupError(f"temporary file for {target_name} has an unexpected identity")
    return _directory_identity(metadata)


def _verify_temporary_entry(
    path: Path,
    temporary_name: str,
    state_descriptor: int | None,
    expected_identity: tuple[int, int],
) -> None:
    temporary = Path(temporary_name) if state_descriptor is None else path.parent / temporary_name
    _verify_file_entry(
        temporary,
        temporary_name,
        state_descriptor,
        expected_identity,
        f"temporary file for {path.name}",
    )


def _replace_temporary_entry(
    path: Path,
    temporary_name: str,
    state_descriptor: int | None,
) -> None:
    if state_descriptor is None:
        Path(temporary_name).replace(path)
    else:
        os.replace(
            temporary_name,
            path.name,
            src_dir_fd=state_descriptor,
            dst_dir_fd=state_descriptor,
        )


def _verify_file_entry(
    path: Path,
    name: str,
    descriptor: int | None,
    expected_identity: tuple[int, int],
    label: str,
) -> None:
    try:
        metadata = _entry_stat(path, name, descriptor)
    except OSError as error:
        raise SetupError(f"cannot inspect {label}: {error}") from error
    if _regular_file_identity(metadata, label) != expected_identity:
        raise SetupError(f"{label} changed during state update")


def _verify_file_content(
    path: Path,
    name: str,
    state_descriptor: int | None,
    expected_identity: tuple[int, int],
    label: str,
    expected_content: bytes,
) -> None:
    try:
        descriptor = _open_file_entry(path, name, state_descriptor)
    except OSError as error:
        raise SetupError(f"cannot open {label}: {error}") from error
    try:
        if _regular_file_identity(os.fstat(descriptor), label) != expected_identity:
            raise SetupError(f"{label} changed during state update")
        _verify_file_entry(path, name, state_descriptor, expected_identity, label)
        with os.fdopen(descriptor, "rb") as stream:
            descriptor = -1
            if stream.read() != expected_content:
                raise SetupError(f"{label} content changed during state update")
            if _regular_file_identity(os.fstat(stream.fileno()), label) != expected_identity:
                raise SetupError(f"{label} changed during state update")
            _verify_file_entry(path, name, state_descriptor, expected_identity, label)
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _read_file_snapshot(
    path: Path,
    state_descriptor: int | None,
    label: str,
) -> _FileSnapshot:
    try:
        descriptor = _open_file_entry(path, path.name, state_descriptor)
    except OSError as error:
        raise SetupError(f"cannot open {label}: {error}") from error
    try:
        metadata = os.fstat(descriptor)
        identity = _regular_file_identity(metadata, label)
        _verify_file_entry(path, path.name, state_descriptor, identity, label)
        with os.fdopen(descriptor, "rb") as stream:
            descriptor = -1
            content = stream.read()
            if _regular_file_identity(os.fstat(stream.fileno()), label) != identity:
                raise SetupError(f"{label} changed while it was read")
        _verify_file_entry(path, path.name, state_descriptor, identity, label)
    except SetupError:
        raise
    except OSError as error:
        raise SetupError(f"cannot read {label}: {error}") from error
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    return _FileSnapshot(
        version=_FileVersion(content=content, identity=identity),
        access_time_ns=metadata.st_atime_ns,
        modified_time_ns=metadata.st_mtime_ns,
        mode=stat.S_IMODE(metadata.st_mode),
    )


def _decode_object(name: str, content: bytes) -> dict[str, object]:
    try:
        value: object = json.loads(content)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise SetupError(f"cannot read {name}: {error}") from error
    if not isinstance(value, dict):
        raise SetupError(f"{name} must contain a JSON object")
    result: dict[str, object] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            raise SetupError(f"{name} contains a non-string key")
        result[key] = item
    return result


def _verify_file_version(
    path: Path,
    name: str,
    state_descriptor: int | None,
    expected: _FileVersion,
    label: str,
) -> None:
    _verify_file_content(
        path,
        name,
        state_descriptor,
        expected.identity,
        label,
        expected.content,
    )


def _file_version_matches(
    path: Path,
    name: str,
    state_descriptor: int | None,
    expected: _FileVersion,
) -> bool:
    try:
        _verify_file_version(path, name, state_descriptor, expected, name)
    except SetupError:
        return False
    return True


def _restore_file_snapshot(
    path: Path,
    name: str,
    state_descriptor: int | None,
    snapshot: _FileSnapshot,
    expected_current: _FileVersion,
) -> None:
    if not _file_version_matches(path, name, state_descriptor, expected_current):
        return
    identity = _write_bytes_in_state(
        path,
        snapshot.version.content,
        state_descriptor,
        expected_current=expected_current,
    )
    try:
        if state_descriptor is None:
            os.chmod(path, snapshot.mode)
            os.utime(
                path,
                ns=(snapshot.access_time_ns, snapshot.modified_time_ns),
            )
        else:
            os.chmod(name, snapshot.mode, dir_fd=state_descriptor, follow_symlinks=False)
            os.utime(
                name,
                ns=(snapshot.access_time_ns, snapshot.modified_time_ns),
                dir_fd=state_descriptor,
                follow_symlinks=False,
            )
    except OSError as error:
        raise SetupError(f"cannot restore {name}: {error}") from error
    _verify_file_version(
        path,
        name,
        state_descriptor,
        _FileVersion(content=snapshot.version.content, identity=identity),
        name,
    )


def _open_file_entry(path: Path, name: str, state_descriptor: int | None) -> int:
    if os.name == "nt":
        return _open_windows_file(path)
    flags = os.O_RDONLY | int(getattr(os, "O_NOFOLLOW", 0))
    return os.open(name, flags, dir_fd=state_descriptor)


def _regular_file_identity(metadata: os.stat_result, label: str) -> tuple[int, int]:
    if (
        not stat.S_ISREG(metadata.st_mode)
        or is_link_like_stat(metadata)
        or int(metadata.st_nlink) != 1
    ):
        raise SetupError(f"{label} must remain a single-link regular file")
    return _directory_identity(metadata)


def _discard_temporary_entry(
    path: Path,
    temporary_name: str,
    state_descriptor: int | None,
    expected_identity: tuple[int, int] | None,
) -> None:
    if expected_identity is None:
        return
    temporary = Path(temporary_name) if state_descriptor is None else path.parent / temporary_name
    try:
        metadata = _entry_stat(temporary, temporary_name, state_descriptor)
        if _regular_file_identity(metadata, "temporary file") != expected_identity:
            return
        _unlink_entry(temporary, temporary_name, state_descriptor)
    except (OSError, SetupError):
        pass


@contextmanager
def _protected_project_directory(path: Path) -> Iterator[int | None]:
    entry_identity = _project_entry_identity(path)
    if os.name == "nt":
        handle = _open_windows_directory(path)
        try:
            identity = _validate_windows_directory_handle(handle, path, "project root")
            if identity != entry_identity:
                raise SetupError("project root changed before it was opened")
            yield None
        finally:
            try:
                if _project_entry_identity(path) != entry_identity:
                    raise SetupError("project root changed during state access")
            finally:
                os.close(handle)
        return

    descriptor = _open_posix_directory(path)
    try:
        opened = os.fstat(descriptor)
        if _directory_identity(opened) != entry_identity:
            raise SetupError("project root changed before it was opened")
        yield descriptor
    finally:
        try:
            if _project_entry_identity(path) != entry_identity:
                raise SetupError("project root changed during state access")
        finally:
            os.close(descriptor)


@contextmanager
def _protected_state_directory(
    root: Path,
    root_descriptor: int | None,
    *,
    expected_identity: tuple[int, int] | None = None,
) -> Iterator[tuple[int | None, tuple[int, int]]]:
    state = root / STATE_DIRECTORY
    entry_identity = _state_entry_identity(state, root_descriptor)
    if expected_identity is not None and entry_identity != expected_identity:
        raise SetupError(f"{STATE_DIRECTORY} changed before it was opened")
    if os.name == "nt":
        handle = _open_windows_directory(state)
        try:
            identity = _validate_windows_directory_handle(handle, state, STATE_DIRECTORY)
            if identity != entry_identity:
                raise SetupError(f"{STATE_DIRECTORY} changed during setup")
            yield None, identity
        finally:
            try:
                if _state_entry_identity(state, root_descriptor) != entry_identity:
                    raise SetupError(f"{STATE_DIRECTORY} changed during state access")
            finally:
                os.close(handle)
        return

    if root_descriptor is None:
        raise SetupError("project root descriptor is unavailable")
    descriptor = _open_posix_directory(STATE_DIRECTORY, dir_fd=root_descriptor)
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISDIR(metadata.st_mode) or is_link_like_stat(metadata):
            raise SetupError(f"{STATE_DIRECTORY} must remain a real directory")
        identity = _directory_identity(metadata)
        if identity != entry_identity:
            raise SetupError(f"{STATE_DIRECTORY} changed during setup")
        yield descriptor, identity
    finally:
        try:
            if _state_entry_identity(state, root_descriptor) != entry_identity:
                raise SetupError(f"{STATE_DIRECTORY} changed during state access")
        finally:
            os.close(descriptor)


def _open_posix_directory(path: str | Path, *, dir_fd: int | None = None) -> int:
    flags = os.O_RDONLY | int(getattr(os, "O_DIRECTORY", 0))
    flags |= int(getattr(os, "O_NOFOLLOW", 0))
    try:
        return os.open(path, flags, dir_fd=dir_fd)
    except OSError as error:
        raise SetupError(f"cannot protect {STATE_DIRECTORY}: {error}") from error


def _open_windows_directory(path: Path) -> int:
    try:
        return _open_windows_handle(
            path,
            desired_access=0x00000001,
            share_mode=0x00000001 | 0x00000002,
            flags=0x02000000 | 0x00200000,
        )
    except OSError as error:
        raise SetupError(f"cannot protect {STATE_DIRECTORY}: {error}") from error


def _open_windows_file(path: Path) -> int:
    return _open_windows_handle(
        path,
        desired_access=0x80000000,
        share_mode=0x00000001,
        flags=0x00200000,
    )


def _open_windows_handle(
    path: Path,
    *,
    desired_access: int,
    share_mode: int,
    flags: int,
) -> int:
    if sys.platform != "win32":
        raise OSError("Windows state handles are unavailable")
    import ctypes
    import msvcrt

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create_file = kernel32.CreateFileW
    create_file.argtypes = (
        ctypes.c_wchar_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_void_p,
    )
    create_file.restype = ctypes.c_void_p
    value = str(path.absolute())
    if value.startswith("\\\\?\\"):
        pass
    elif value.startswith("\\\\"):
        value = f"\\\\?\\UNC\\{value[2:]}"
    else:
        value = f"\\\\?\\{value}"
    handle = create_file(
        value,
        desired_access,
        share_mode,
        None,
        3,
        flags,
        None,
    )
    invalid_handle = ctypes.c_void_p(-1).value
    if handle is None or handle == invalid_handle:
        error_code = ctypes.get_last_error()
        raise ctypes.WinError(error_code)
    try:
        return msvcrt.open_osfhandle(int(handle), os.O_RDONLY)
    except OSError:
        kernel32.CloseHandle(ctypes.c_void_p(handle))
        raise


def _validate_windows_directory_handle(
    descriptor: int,
    path: Path,
    label: str,
) -> tuple[int, int]:
    try:
        opened = os.fstat(descriptor)
        current = path.stat(follow_symlinks=False)
        final_path = path.resolve(strict=True)
    except OSError as error:
        raise SetupError(f"cannot inspect {label}: {error}") from error
    if not _same_directory(opened, current):
        raise SetupError(f"{label} changed while being inspected")
    if os.path.normcase(str(final_path)) != os.path.normcase(str(path.absolute())):
        raise SetupError(f"{label} changed to a different location")
    return _directory_identity(opened)


def _same_directory(left: os.stat_result, right: os.stat_result) -> bool:
    return (
        stat.S_ISDIR(left.st_mode)
        and stat.S_ISDIR(right.st_mode)
        and not is_link_like_stat(left)
        and not is_link_like_stat(right)
        and _directory_identity(left) == _directory_identity(right)
    )


def _directory_identity(metadata: os.stat_result) -> tuple[int, int]:
    return int(metadata.st_dev), int(metadata.st_ino)


def _project_entry_identity(path: Path) -> tuple[int, int]:
    try:
        metadata = path.stat(follow_symlinks=False)
    except OSError as error:
        raise SetupError(f"cannot inspect project root: {error}") from error
    if has_link_like_component(path) or not stat.S_ISDIR(metadata.st_mode):
        raise SetupError("project root must remain a real directory")
    return _directory_identity(metadata)


def _state_entry_exists(state: Path, root_descriptor: int | None) -> tuple[int, int] | None:
    try:
        return _state_entry_identity(state, root_descriptor)
    except FileNotFoundError:
        return None


def _create_state_directory(state: Path, root_descriptor: int | None) -> None:
    _create_entry(state, STATE_DIRECTORY, root_descriptor)


def _state_entry_identity(state: Path, root_descriptor: int | None) -> tuple[int, int]:
    try:
        metadata = _entry_stat(state, STATE_DIRECTORY, root_descriptor)
    except FileNotFoundError:
        raise
    except OSError as error:
        raise SetupError(f"cannot inspect {STATE_DIRECTORY}: {error}") from error
    if not stat.S_ISDIR(metadata.st_mode) or is_link_like_stat(metadata):
        raise SetupError(f"{STATE_DIRECTORY} must remain a real directory")
    return _directory_identity(metadata)


def _entry_stat(path: Path, name: str, descriptor: int | None) -> os.stat_result:
    if descriptor is None:
        return path.stat(follow_symlinks=False)
    return os.stat(name, dir_fd=descriptor, follow_symlinks=False)


def _create_entry(path: Path, name: str, descriptor: int | None) -> None:
    path.mkdir() if descriptor is None else os.mkdir(name, dir_fd=descriptor)


def _unlink_entry(path: Path, name: str, descriptor: int | None) -> None:
    path.unlink(missing_ok=True) if descriptor is None else os.unlink(name, dir_fd=descriptor)


def _validate_state(
    state: Path,
    state_descriptor: int | None = None,
    *,
    config: ConfigData | None = None,
) -> ConfigData:
    if state_descriptor is None and (is_link_like(state) or not state.is_dir()):
        raise SetupError(f"{STATE_DIRECTORY} must be a real directory")

    if config is None:
        config = _parse_config(_read_object(state / "config.json", state_descriptor))

    _parse_notes(_read_object(state / "notes.json", state_descriptor))

    language = state / "language.json"
    if _entry_exists(language, "language.json", state_descriptor):
        try:
            parse_language_settings(_read_object(language, state_descriptor))
        except ValueError as error:
            raise SetupError(str(error)) from error

    exports = state / "exports"
    try:
        exports_metadata = _entry_stat(exports, "exports", state_descriptor)
    except OSError as error:
        raise SetupError(f"cannot inspect exports: {error}") from error
    if not stat.S_ISDIR(exports_metadata.st_mode) or is_link_like_stat(exports_metadata):
        raise SetupError("exports must be a real directory")

    index = state / "index.json"
    if _entry_exists(index, "index.json", state_descriptor):
        try:
            index_data = _read_object(index, state_descriptor)
        except SetupError as error:
            raise IndexStateError(str(error)) from error
        if not is_rebuildable_index_version(index_data.get("index_version")):
            raise IndexStateError(
                f"index.json is not compatible with index version {INDEX_VERSION}"
            )
    return config


def _parse_config(value: dict[str, object]) -> ConfigData:
    if set(value) != {"boundaries", "default_excludes", "schema_version"}:
        raise SetupError("config.json has an incompatible schema")
    if not _is_version_one(value["schema_version"]):
        raise SetupError("config.json has an unsupported schema version")

    excludes = value["default_excludes"]
    if not isinstance(excludes, list) or not all(isinstance(item, str) for item in excludes):
        raise SetupError("config.json default_excludes must be a string array")
    if tuple(excludes) != DEFAULT_EXCLUDES:
        raise SetupError("config.json default exclusions do not match version 1")

    raw_boundaries = value["boundaries"]
    if not isinstance(raw_boundaries, list):
        raise SetupError("config.json boundaries must be an array")
    boundaries = [_parse_boundary(item) for item in raw_boundaries]
    if len({item["path"] for item in boundaries}) != len(boundaries):
        raise SetupError("config.json contains duplicate boundary paths")
    if len({item["alias"] for item in boundaries}) != len(boundaries):
        raise SetupError("config.json contains duplicate boundary aliases")
    return ConfigData(
        boundaries=boundaries,
        default_excludes=list(excludes),
        schema_version=1,
    )


def _parse_boundary(value: object) -> BoundaryData:
    if not isinstance(value, dict):
        raise SetupError("config.json boundary must be an object")
    boundary: dict[str, object] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            raise SetupError("config.json boundary contains a non-string key")
        boundary[key] = item
    if set(boundary) != {"alias", "description", "path"}:
        raise SetupError("config.json boundary has an incompatible schema")
    alias = boundary["alias"]
    description = boundary["description"]
    path = boundary["path"]
    if not isinstance(alias, str) or not isinstance(description, str) or not isinstance(path, str):
        raise SetupError("config.json boundary fields must be strings")
    if not is_valid_boundary_alias(alias):
        raise SetupError("config.json boundary alias is invalid")
    if not description.strip():
        raise SetupError("config.json boundary description is empty")
    if not _is_stored_boundary_path(path):
        raise SetupError("config.json boundary path is invalid")
    return BoundaryData(alias=alias, description=description, path=path)


def _parse_notes(value: dict[str, object]) -> NotesData:
    if set(value) != {"notes", "notes_version"}:
        raise SetupError("notes.json has an incompatible schema")
    if not _is_version_one(value["notes_version"]):
        raise SetupError("notes.json has an unsupported version")
    raw_notes = value["notes"]
    if not isinstance(raw_notes, list):
        raise SetupError("notes.json notes must be an array")
    notes = [_parse_note(item) for item in raw_notes]
    if len({note["id"] for note in notes}) != len(notes):
        raise SetupError("notes.json contains duplicate note IDs")
    return NotesData(notes=notes, notes_version=1)


def _parse_note(value: object) -> HumanNoteData:
    if not isinstance(value, dict):
        raise SetupError("notes.json note must be an object")
    note: dict[str, object] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            raise SetupError("notes.json note contains a non-string key")
        note[key] = item
    if set(note) != {"comment", "id", "path"}:
        raise SetupError("notes.json note has an incompatible schema")
    comment = note["comment"]
    note_id = note["id"]
    path = note["path"]
    if not isinstance(comment, str) or not isinstance(note_id, str) or not isinstance(path, str):
        raise SetupError("notes.json note fields must be strings")
    if not comment.strip():
        raise SetupError("notes.json note comment is empty")
    if _NOTE_ID_PATTERN.fullmatch(note_id) is None:
        raise SetupError("notes.json note ID is invalid")
    if not _is_stored_boundary_path(path):
        raise SetupError("notes.json note path is invalid")
    return HumanNoteData(comment=comment, id=note_id, path=path)


def _is_stored_boundary_path(path: str) -> bool:
    if not path or "\\" in path:
        return False
    posix_path = PurePosixPath(path)
    windows_path = PureWindowsPath(path)
    if posix_path.is_absolute() or windows_path.drive or windows_path.root:
        return False
    if ".." in posix_path.parts:
        return False
    return posix_path.as_posix() == path


def _is_version_one(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value == 1


def _entry_exists(path: Path, name: str, descriptor: int | None) -> bool:
    try:
        _entry_stat(path, name, descriptor)
    except FileNotFoundError:
        return False
    except OSError as error:
        raise SetupError(f"cannot inspect {name}: {error}") from error
    return True


def _read_object(path: Path, state_descriptor: int | None = None) -> dict[str, object]:
    try:
        if state_descriptor is None:
            if is_link_like(path) or not path.is_file():
                raise SetupError(f"{path.name} must be a real file")
            text = path.read_text(encoding="utf-8")
        else:
            flags = os.O_RDONLY | int(getattr(os, "O_NOFOLLOW", 0))
            entry_metadata = _entry_stat(path, path.name, state_descriptor)
            descriptor = os.open(path.name, flags, dir_fd=state_descriptor)
            try:
                opened_metadata = os.fstat(descriptor)
                if (
                    is_link_like_stat(entry_metadata)
                    or not stat.S_ISREG(opened_metadata.st_mode)
                    or _directory_identity(entry_metadata) != _directory_identity(opened_metadata)
                ):
                    raise SetupError(f"{path.name} must be a real file")
                with os.fdopen(descriptor, encoding="utf-8") as stream:
                    descriptor = -1
                    text = stream.read()
            finally:
                if descriptor >= 0:
                    os.close(descriptor)
        value: object = json.loads(text)
    except SetupError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise SetupError(f"cannot read {path.name}: {error}") from error
    if not isinstance(value, dict):
        raise SetupError(f"{path.name} must contain a JSON object")

    result: dict[str, object] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            raise SetupError(f"{path.name} contains a non-string key")
        result[key] = item
    return result
