from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import TypedDict

from silobrief.index_version import INDEX_VERSION, is_rebuildable_index_version
from silobrief.language import (
    LanguageSettings,
    default_language_settings,
    parse_language_settings,
)
from silobrief.path_safety import has_link_like_component, is_link_like

STATE_DIRECTORY = ".silobrief"
_BOUNDARY_ALIAS_PATTERN = re.compile(r"[a-z0-9-]{1,40}")
_NOTE_ID_PATTERN = re.compile(r"note-[0-9a-f]{64}")
DEFAULT_EXCLUDES = (
    ".git/",
    ".silobrief/",
    "__pycache__/",
    ".venv/",
    "venv/",
    "build/",
    "dist/",
)


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


def setup_project(project: Path) -> bool:
    root = _project_root(project)
    state = root / STATE_DIRECTORY

    if state.exists() or is_link_like(state):
        _validate_state(state)
        return False

    try:
        state.mkdir()
    except FileExistsError:
        _validate_state(state)
        return False
    except OSError as error:
        raise SetupError(f"cannot create {STATE_DIRECTORY}: {error}") from error

    try:
        (state / "exports").mkdir()
        _write_json(
            state / "config.json",
            ConfigData(
                boundaries=[],
                default_excludes=list(DEFAULT_EXCLUDES),
                schema_version=1,
            ),
        )
        _write_json(state / "notes.json", NotesData(notes=[], notes_version=1))
        _write_json(state / "language.json", default_language_settings())
    except OSError as error:
        if not is_link_like(state):
            shutil.rmtree(state, ignore_errors=True)
        raise SetupError(f"cannot initialize {STATE_DIRECTORY}: {error}") from error
    return True


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


def is_valid_boundary_alias(alias: str) -> bool:
    return _BOUNDARY_ALIAS_PATTERN.fullmatch(alias) is not None


def _write_json(
    path: Path,
    value: ConfigData | NotesData | LanguageSettings | dict[str, object],
) -> None:
    content = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    path.write_text(content, encoding="utf-8", newline="\n")


def _write_json_atomic(
    path: Path,
    value: ConfigData | NotesData | LanguageSettings | dict[str, object],
) -> None:
    content = (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )
    _write_bytes_atomic(path, content)


def _write_bytes_atomic(path: Path, content: bytes) -> None:
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            dir=path.parent,
            prefix=f".{path.name}-",
            suffix=".tmp",
        )
    except OSError as error:
        raise SetupError(f"cannot create temporary file for {path.name}: {error}") from error
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
        temporary.replace(path)
    except OSError as error:
        raise SetupError(f"cannot update {path.name}: {error}") from error
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def _validate_state(state: Path) -> ConfigData:
    if is_link_like(state) or not state.is_dir():
        raise SetupError(f"{STATE_DIRECTORY} must be a real directory")

    config = _parse_config(_read_object(state / "config.json"))

    _parse_notes(_read_object(state / "notes.json"))

    language = state / "language.json"
    if language.exists() or is_link_like(language):
        try:
            parse_language_settings(_read_object(language))
        except ValueError as error:
            raise SetupError(str(error)) from error

    exports = state / "exports"
    if is_link_like(exports) or not exports.is_dir():
        raise SetupError("exports must be a real directory")

    index = state / "index.json"
    if index.exists() or is_link_like(index):
        try:
            index_data = _read_object(index)
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


def _read_object(path: Path) -> dict[str, object]:
    if is_link_like(path) or not path.is_file():
        raise SetupError(f"{path.name} must be a real file")

    try:
        value: object = json.loads(path.read_text(encoding="utf-8"))
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
