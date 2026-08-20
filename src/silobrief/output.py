from __future__ import annotations

import errno
import os
import stat
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import TextIO

from silobrief.current_index import (
    CurrentIndexApproval,
    CurrentIndexError,
    revalidate_current_index_approval,
    seal_current_index_approval,
)
from silobrief.language import Language, localized
from silobrief.path_safety import has_link_like_component, is_link_like, is_link_like_stat
from silobrief.renderer import RenderedBrief
from silobrief.sources import (
    SourceCollectionError,
    SourceRootIdentity,
    SourceSnapshot,
    load_source_config,
    snapshot_sources,
)
from silobrief.state import STATE_DIRECTORY, SetupError
from silobrief.terminal import escape_terminal_preview


class OutputBlockedError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class WrittenBrief:
    main: Path


@dataclass(frozen=True, slots=True)
class _FileIdentity:
    device: int
    inode: int


@dataclass(slots=True)
class _CreatedFile:
    path: Path
    descriptor: int
    identity: _FileIdentity
    published: bool


@dataclass(slots=True)
class _OutputDirectoryGuard:
    descriptor: int | None
    identity: tuple[int, int]
    created: _CreatedFile | None = None
    revalidate: Callable[[], None] | None = None
    seal: Callable[[], None] | None = None


def approve_and_write(
    root: Path,
    output_text: str,
    rendered: RenderedBrief,
    *,
    start: Path,
    input_stream: TextIO,
    output_stream: TextIO,
    source_snapshot: SourceSnapshot | None = None,
    approval_state: CurrentIndexApproval | None = None,
    language: Language = "en",
) -> WrittenBrief:
    if not input_stream.isatty() or not output_stream.isatty():
        raise OutputBlockedError(
            localized(
                language,
                "approval requires interactive input and output",
                "승인에는 대화형 입력과 출력이 필요합니다",
            )
        )
    if type(rendered) is not RenderedBrief:
        raise OutputBlockedError("output requires a rendered brief")
    index_path = root / STATE_DIRECTORY / "index.json"
    if approval_state is None and (index_path.exists() or is_link_like(index_path)):
        raise OutputBlockedError("output requires the loaded index approval state")
    if approval_state is not None and (
        source_snapshot is None
        or source_snapshot.digest != approval_state.index.source_digest
        or source_snapshot.root_identity != approval_state.root_identity
    ):
        raise OutputBlockedError("output approval state does not match the reviewed sources")

    with _output_path(root, start, output_text) as (destination, directory_guard):
        baseline = source_snapshot if source_snapshot is not None else _snapshot(root)

        def revalidate() -> None:
            _revalidate_project(root, baseline, approval_state, language)

        directory_guard.revalidate = revalidate
        if approval_state is not None:

            def seal() -> None:
                _revalidate_project(root, baseline, approval_state, language)
                _revalidate_policy(root, approval_state, language, seal=True)

            directory_guard.seal = seal
        revalidate()
        try:
            output_stream.write(escape_terminal_preview(rendered.markdown))
            revalidate()
            output_stream.write(
                "\n"
                + localized(
                    language,
                    "Type exactly WRITE to create the Markdown file: ",
                    "Markdown 파일을 만들려면 WRITE를 정확히 입력하세요: ",
                )
            )
            output_stream.flush()
            approval = input_stream.readline()
        except SetupError:
            if approval_state is not None:
                _revalidate_policy(root, approval_state, language)
            raise
        except OSError as error:
            raise OutputBlockedError(f"cannot complete interactive approval: {error}") from error
        if _without_line_ending(approval) != "WRITE":
            raise OutputBlockedError(
                localized(
                    language,
                    "output was not approved with exact WRITE",
                    "WRITE가 정확히 입력되지 않아 출력을 승인하지 않았습니다",
                )
            )

        revalidate()

        _write_new_file(
            destination,
            rendered.markdown,
            directory_guard=directory_guard,
        )
    return WrittenBrief(destination)


@contextmanager
def _output_path(
    root: Path,
    start: Path,
    output_text: str,
) -> Iterator[tuple[Path, _OutputDirectoryGuard]]:
    if not isinstance(output_text, str) or not output_text:
        raise OutputBlockedError("output path must not be empty")
    if "/" in output_text and "\\" in output_text:
        raise OutputBlockedError("output path must not mix path separators")

    posix = PurePosixPath(output_text)
    windows = PureWindowsPath(output_text)
    if ".." in posix.parts or ".." in windows.parts:
        raise OutputBlockedError("output path must not contain ..")
    if _uses_foreign_windows_path(output_text, platform=os.name):
        raise OutputBlockedError("output path uses a Windows absolute path on this system")

    try:
        requested = Path(output_text)
    except (OSError, ValueError) as error:
        raise OutputBlockedError(f"output path is invalid: {error}") from error
    if requested.suffix != ".md":
        raise OutputBlockedError("output path must use the .md extension")

    resolved_root, root_identity = _real_directory(root, "project root")
    resolved_start, _start_identity = _real_directory(start, "current directory")
    try:
        resolved_start.relative_to(resolved_root)
    except ValueError as error:
        raise OutputBlockedError("current directory is outside the project root") from error

    candidate = requested if requested.is_absolute() else resolved_start / requested
    candidate = candidate.absolute()
    if is_link_like(candidate):
        raise OutputBlockedError("output path must not be a symbolic link or reparse point")
    if candidate.exists():
        raise OutputBlockedError("output path already exists")
    if has_link_like_component(candidate.parent):
        raise OutputBlockedError("output path contains a symbolic link or reparse point")

    with _protected_output_directory(candidate.parent) as directory_guard:
        parent, parent_identity = _real_parent(candidate.parent)
        if parent_identity != directory_guard.identity:
            raise OutputBlockedError("output parent changed during path approval")
        if not _same_path_identity(resolved_root, root_identity):
            raise OutputBlockedError("project root changed during path approval")
        destination = _available_path(parent / candidate.name, resolved_root)
        yield destination, directory_guard


def _available_path(destination: Path, root: Path) -> Path:
    if is_link_like(destination):
        raise OutputBlockedError("output path must not be a symbolic link or reparse point")
    if destination.exists():
        raise OutputBlockedError("output path already exists")
    _require_allowed_location(destination, root)
    return destination


def _uses_foreign_windows_path(path: str, *, platform: str) -> bool:
    windows = PureWindowsPath(path)
    return platform != "nt" and bool(windows.drive or "\\" in path)


def _real_directory(path: Path, label: str) -> tuple[Path, tuple[int, int]]:
    try:
        before = path.stat(follow_symlinks=False)
    except OSError as error:
        raise OutputBlockedError(f"cannot inspect {label}: {error}") from error
    if has_link_like_component(path) or not _real_directory_metadata(before):
        raise OutputBlockedError(f"{label} must be a real directory")
    try:
        resolved = path.resolve(strict=True)
        after = path.stat(follow_symlinks=False)
    except OSError as error:
        raise OutputBlockedError(f"cannot resolve {label}: {error}") from error
    if not _same_real_directory(before, after):
        raise OutputBlockedError(f"{label} changed while being inspected")
    return resolved, _directory_identity(after)


def _real_parent(parent: Path) -> tuple[Path, tuple[int, int]]:
    try:
        before = parent.stat(follow_symlinks=False)
    except OSError as error:
        raise OutputBlockedError(f"cannot inspect output parent: {error}") from error
    current = Path(parent.anchor)
    for part in parent.parts[1:]:
        current /= part
        if is_link_like(current):
            raise OutputBlockedError("output path contains a symbolic link or reparse point")
    if not _real_directory_metadata(before):
        raise OutputBlockedError("output parent must be an existing directory")
    try:
        resolved = parent.resolve(strict=True)
        after = parent.stat(follow_symlinks=False)
    except OSError as error:
        raise OutputBlockedError(f"cannot resolve output parent: {error}") from error
    if not _same_real_directory(before, after):
        raise OutputBlockedError("output parent changed while being inspected")
    return resolved, _directory_identity(after)


@contextmanager
def _protected_output_directory(
    path: Path,
) -> Iterator[_OutputDirectoryGuard]:
    if os.name == "nt":
        parent_descriptor = _open_windows_directory(path)
        write_descriptor = None
    else:
        try:
            parent_descriptor = _open_posix_directory(path)
        except OSError as error:
            raise OutputBlockedError(f"cannot protect output parent: {error}") from error
        write_descriptor = parent_descriptor

    try:
        if os.name == "nt" and _normalized_windows_path(
            _windows_handle_path(parent_descriptor)
        ) != _normalized_windows_path(path):
            raise OutputBlockedError("output parent must remain a real directory")
        if not _same_directory(path, parent_descriptor):
            raise OutputBlockedError("output parent must remain a real directory")
        guard = _OutputDirectoryGuard(
            write_descriptor,
            _directory_identity(os.fstat(parent_descriptor)),
        )
        try:
            yield guard
            if not _same_directory(path, parent_descriptor):
                raise OutputBlockedError("output parent changed after creating the file")
            if guard.created is None or not _same_created_file(
                guard.created,
                directory_descriptor=write_descriptor,
            ):
                raise OutputBlockedError("output file changed after creation")
            if guard.revalidate is not None:
                guard.revalidate()
            _publish_created_file(
                guard.created,
                directory_descriptor=write_descriptor,
            )
            if not _same_directory(path, parent_descriptor):
                raise OutputBlockedError("output parent changed while publishing the file")
            if guard.seal is not None:
                guard.seal()
            elif guard.revalidate is not None:
                guard.revalidate()
            _close_created_file(guard.created)
        except BaseException:
            _abort_created_file(guard)
            raise
    finally:
        os.close(parent_descriptor)


def _open_posix_directory(path: Path) -> int:
    flags = int(getattr(os, "O_PATH", os.O_RDONLY))
    flags |= int(getattr(os, "O_DIRECTORY", 0))
    flags |= int(getattr(os, "O_NOFOLLOW", 0))
    descriptor = os.open(path.anchor, flags)
    try:
        root_metadata = os.fstat(descriptor)
        if not stat.S_ISDIR(root_metadata.st_mode) or is_link_like_stat(root_metadata):
            raise OutputBlockedError("output parent must remain a real directory")
        for part in path.parts[1:]:
            next_descriptor: int | None = None
            try:
                before = os.stat(part, dir_fd=descriptor, follow_symlinks=False)
                if not _real_directory_metadata(before):
                    raise OutputBlockedError("output parent must remain a real directory")
                next_descriptor = os.open(part, flags, dir_fd=descriptor)
                opened = os.fstat(next_descriptor)
                after = os.stat(part, dir_fd=descriptor, follow_symlinks=False)
                if not (
                    _same_real_directory(before, opened) and _same_real_directory(opened, after)
                ):
                    raise OutputBlockedError("output parent changed while being protected")
            except BaseException:
                if next_descriptor is not None:
                    os.close(next_descriptor)
                raise
            os.close(descriptor)
            descriptor = next_descriptor
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _real_directory_metadata(metadata: os.stat_result) -> bool:
    return stat.S_ISDIR(metadata.st_mode) and not is_link_like_stat(metadata)


def _same_real_directory(left: os.stat_result, right: os.stat_result) -> bool:
    return (
        _real_directory_metadata(left)
        and _real_directory_metadata(right)
        and left.st_dev == right.st_dev
        and left.st_ino == right.st_ino
    )


def _directory_identity(metadata: os.stat_result) -> tuple[int, int]:
    return int(metadata.st_dev), int(metadata.st_ino)


def _same_path_identity(path: Path, identity: tuple[int, int]) -> bool:
    try:
        metadata = path.stat(follow_symlinks=False)
        return (
            not has_link_like_component(path)
            and _real_directory_metadata(metadata)
            and _directory_identity(metadata) == identity
        )
    except OSError:
        return False


def _open_windows_directory(path: Path) -> int:
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
    if value.startswith("\\\\"):
        value = f"\\\\?\\UNC\\{value[2:]}"
    elif not value.startswith("\\\\?\\"):
        value = f"\\\\?\\{value}"
    handle = create_file(
        value,
        0x00010000 | 0x00000080,
        0x00000001 | 0x00000002,
        None,
        3,
        0x02000000 | 0x00200000,
        None,
    )
    invalid_handle = ctypes.c_void_p(-1).value
    if handle is None or handle == invalid_handle:
        error_code = ctypes.get_last_error()
        raise OutputBlockedError(f"cannot protect output parent: Windows error {error_code}")
    try:
        return msvcrt.open_osfhandle(int(handle), os.O_RDONLY)
    except BaseException:
        kernel32.CloseHandle(ctypes.c_void_p(handle))
        raise


def _windows_handle_path(descriptor: int) -> Path:
    import ctypes
    import msvcrt

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    final_path = kernel32.GetFinalPathNameByHandleW
    final_path.argtypes = (
        ctypes.c_void_p,
        ctypes.c_wchar_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
    )
    final_path.restype = ctypes.c_uint32
    buffer = ctypes.create_unicode_buffer(32768)
    handle = msvcrt.get_osfhandle(descriptor)
    length = final_path(ctypes.c_void_p(handle), buffer, len(buffer), 0)
    if length == 0 or length >= len(buffer):
        error_code = ctypes.get_last_error()
        raise OutputBlockedError(
            f"cannot resolve protected output parent: Windows error {error_code}"
        )
    value = buffer.value
    if value.startswith("\\\\?\\UNC\\"):
        value = f"\\\\{value[8:]}"
    elif value.startswith("\\\\?\\"):
        value = value[4:]
    return Path(value)


def _normalized_windows_path(path: Path) -> str:
    value = str(path.absolute())
    if value.startswith("\\\\?\\UNC\\"):
        value = f"\\\\{value[8:]}"
    elif value.startswith("\\\\?\\"):
        value = value[4:]
    return os.path.normcase(os.path.normpath(value))


def _require_allowed_location(destination: Path, root: Path) -> None:
    try:
        destination.relative_to(root)
    except ValueError:
        return

    exports = root / STATE_DIRECTORY / "exports"
    if is_link_like(exports) or not exports.is_dir():
        raise OutputBlockedError("project exports must be a real directory")
    try:
        resolved_exports = exports.resolve(strict=True)
        destination.relative_to(resolved_exports)
    except (OSError, ValueError) as error:
        raise OutputBlockedError(
            f"project output must be inside {STATE_DIRECTORY}/exports"
        ) from error


def _without_line_ending(value: str) -> str:
    if value.endswith("\r\n"):
        return value[:-2]
    if value.endswith(("\r", "\n")):
        return value[:-1]
    return value


def _snapshot(
    root: Path,
    *,
    expected_root_identity: SourceRootIdentity | None = None,
    approval_state: CurrentIndexApproval | None = None,
) -> SourceSnapshot:
    try:
        if approval_state is None:
            config, root_identity = load_source_config(
                root, expected_root_identity=expected_root_identity
            )
        else:
            config, root_identity = approval_state.config, approval_state.root_identity
        descriptor = approval_state._resources.root_fd if approval_state is not None else None
        return snapshot_sources(
            root,
            config,
            expected_root_identity=root_identity,
            protected_root_descriptor=descriptor,
        )
    except (SetupError, SourceCollectionError) as error:
        raise OutputBlockedError(f"cannot revalidate project sources: {error}") from error


def _revalidate_project(
    root: Path,
    baseline: SourceSnapshot,
    approval_state: CurrentIndexApproval | None,
    language: Language,
) -> None:
    if approval_state is not None:
        _revalidate_policy(root, approval_state, language)
    current = _snapshot(
        root,
        expected_root_identity=baseline.root_identity,
        **({"approval_state": approval_state} if approval_state is not None else {}),
    )
    if current.digest != baseline.digest:
        raise OutputBlockedError(
            localized(
                language,
                "project sources changed during review; run sb init",
                "검토 중 프로젝트 소스가 변경되었습니다. sb init을 실행하세요",
            )
        )
    if approval_state is not None:
        _revalidate_policy(root, approval_state, language)


def _revalidate_policy(
    root: Path,
    approval_state: CurrentIndexApproval,
    language: Language,
    seal: bool = False,
) -> None:
    try:
        validator = seal_current_index_approval if seal else revalidate_current_index_approval
        validator(root, approval_state)
    except CurrentIndexError as error:
        raise OutputBlockedError(
            localized(
                language,
                "project settings changed during approval; run sb init",
                "승인 중 프로젝트 설정이 변경되었습니다. sb init을 실행하세요",
            )
        ) from error


def _write_new_file(
    path: Path,
    content: str,
    *,
    directory_guard: _OutputDirectoryGuard,
) -> None:
    try:
        encoded = content.encode("utf-8")
    except UnicodeError as error:
        raise OutputBlockedError("rendered brief is not valid UTF-8 text") from error
    if directory_guard.revalidate is not None:
        directory_guard.revalidate()

    descriptor: int | None = None
    try:
        descriptor, published = _open_new_file(path, directory_guard.descriptor)
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or is_link_like_stat(metadata):
            raise OutputBlockedError("created output must remain a regular file")
        directory_guard.created = _CreatedFile(
            path,
            descriptor,
            _FileIdentity(metadata.st_dev, metadata.st_ino),
            published,
        )
        _write_bytes(descriptor, encoded)
        if directory_guard.revalidate is not None:
            directory_guard.revalidate()
        if directory_guard.descriptor is not None and not _same_directory(
            path.parent, directory_guard.descriptor
        ):
            raise OutputBlockedError("output parent changed while creating the file")
    except FileExistsError as error:
        _cleanup_failed_creation(path, descriptor, directory_guard)
        raise OutputBlockedError("output path already exists") from error
    except OSError as error:
        _cleanup_failed_creation(path, descriptor, directory_guard)
        raise OutputBlockedError(f"cannot create output file: {error}") from error
    except BaseException:
        _cleanup_failed_creation(path, descriptor, directory_guard)
        raise


def _open_new_file(path: Path, directory_descriptor: int | None) -> tuple[int, bool]:
    if os.name == "nt":
        return _open_windows_output_file(path), True
    temporary_flag = int(getattr(os, "O_TMPFILE", 0))
    if directory_descriptor is None or not temporary_flag:
        raise OutputBlockedError("secure POSIX output requires O_TMPFILE support")
    flags = os.O_WRONLY | temporary_flag | int(getattr(os, "O_CLOEXEC", 0))
    try:
        return os.open(".", flags, 0o666, dir_fd=directory_descriptor), False
    except OSError as error:
        if error.errno in (errno.EINVAL, errno.ENOSYS, errno.EOPNOTSUPP):
            raise OutputBlockedError("output filesystem does not support O_TMPFILE") from error
        raise


def _open_windows_output_file(path: Path) -> int:
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
    if value.startswith("\\\\"):
        value = f"\\\\?\\UNC\\{value[2:]}"
    elif not value.startswith("\\\\?\\"):
        value = f"\\\\?\\{value}"
    handle = create_file(
        value,
        0x40000000 | 0x00010000 | 0x00000080,
        0x00000001 | 0x00000002,
        None,
        1,
        0x00000080 | 0x00200000,
        None,
    )
    invalid_handle = ctypes.c_void_p(-1).value
    if handle is None or handle == invalid_handle:
        error_code = ctypes.get_last_error()
        if error_code in (80, 183):
            raise FileExistsError(f"output path already exists: {path}")
        raise OSError(error_code, f"Windows error {error_code}", str(path))
    try:
        flags = os.O_WRONLY | int(getattr(os, "O_BINARY", 0))
        return msvcrt.open_osfhandle(int(handle), flags)
    except BaseException:
        kernel32.CloseHandle(ctypes.c_void_p(handle))
        raise


def _write_bytes(descriptor: int, content: bytes) -> None:
    offset = 0
    while offset < len(content):
        written = os.write(descriptor, content[offset:])
        if written <= 0:
            raise OSError("output write made no progress")
        offset += written


def _cleanup_failed_creation(
    path: Path,
    descriptor: int | None,
    directory_guard: _OutputDirectoryGuard,
) -> None:
    if directory_guard.created is not None:
        _abort_created_file(directory_guard)
        return
    if descriptor is None:
        return
    try:
        metadata = os.fstat(descriptor)
        identity = _FileIdentity(metadata.st_dev, metadata.st_ino)
        _remove_created_file(
            path,
            identity,
            directory_descriptor=directory_guard.descriptor,
        )
    except BaseException:
        pass
    _safe_close_descriptor(descriptor)


def _same_directory(path: Path, descriptor: int) -> bool:
    try:
        return not has_link_like_component(path) and os.path.samestat(
            os.fstat(descriptor),
            path.stat(follow_symlinks=False),
        )
    except OSError:
        return False


def _same_created_file(
    created: _CreatedFile,
    *,
    directory_descriptor: int | None,
) -> bool:
    if created.descriptor < 0:
        return False
    try:
        opened = os.fstat(created.descriptor)
    except OSError:
        return False
    expected_links = 1 if created.published else 0
    same_opened = (
        stat.S_ISREG(opened.st_mode)
        and not is_link_like_stat(opened)
        and opened.st_dev == created.identity.device
        and opened.st_ino == created.identity.inode
        and opened.st_nlink == expected_links
    )
    if not same_opened or not created.published:
        return same_opened
    try:
        current = _output_file_metadata(
            created.path,
            directory_descriptor=directory_descriptor,
        )
    except OSError:
        return False
    return (
        stat.S_ISREG(current.st_mode)
        and not is_link_like_stat(current)
        and current.st_dev == created.identity.device
        and current.st_ino == created.identity.inode
        and current.st_nlink == 1
    )


def _publish_created_file(
    created: _CreatedFile,
    *,
    directory_descriptor: int | None,
) -> None:
    if created.published:
        return
    if directory_descriptor is None:
        raise OutputBlockedError("cannot publish output without its approved parent")
    try:
        os.link(
            f"/proc/self/fd/{created.descriptor}",
            created.path.name,
            dst_dir_fd=directory_descriptor,
            follow_symlinks=True,
        )
    except FileExistsError as error:
        raise OutputBlockedError("output path already exists") from error
    except OSError as error:
        if error.errno == errno.ENOENT:
            raise OutputBlockedError("POSIX output requires /proc/self/fd linking") from error
        raise OutputBlockedError(f"cannot publish output file: {error}") from error
    created.published = True
    if not _same_created_file(
        created,
        directory_descriptor=directory_descriptor,
    ):
        raise OutputBlockedError("output file changed while being published")


def _abort_created_file(guard: _OutputDirectoryGuard) -> None:
    created = guard.created
    if created is None:
        return
    try:
        if created.descriptor >= 0:
            os.ftruncate(created.descriptor, 0)
    except BaseException:
        pass
    deleted_by_handle = os.name == "nt" and _mark_windows_file_for_deletion(created)
    if not deleted_by_handle:
        try:
            _remove_created_file(
                created.path,
                created.identity,
                directory_descriptor=guard.descriptor,
            )
        except BaseException:
            pass
    _safe_close_created_file(created)
    guard.created = None


def _mark_windows_file_for_deletion(created: _CreatedFile) -> bool:
    if created.descriptor < 0:
        return False
    try:
        import ctypes
        import msvcrt

        class _FileDispositionInfo(ctypes.Structure):
            _fields_ = (("delete_file", ctypes.c_ubyte),)

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        set_information = kernel32.SetFileInformationByHandle
        set_information.argtypes = (
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_void_p,
            ctypes.c_uint32,
        )
        set_information.restype = ctypes.c_int
        information = _FileDispositionInfo(1)
        handle = msvcrt.get_osfhandle(created.descriptor)
        return bool(
            set_information(
                ctypes.c_void_p(handle),
                4,
                ctypes.byref(information),
                ctypes.sizeof(information),
            )
        )
    except BaseException:
        return False


def _close_created_file(created: _CreatedFile) -> None:
    descriptor = created.descriptor
    if descriptor < 0:
        return
    created.descriptor = -1
    os.close(descriptor)


def _safe_close_created_file(created: _CreatedFile) -> None:
    try:
        _close_created_file(created)
    except BaseException:
        pass


def _safe_close_descriptor(descriptor: int) -> None:
    try:
        os.close(descriptor)
    except BaseException:
        pass


def _output_file_metadata(
    path: Path,
    *,
    directory_descriptor: int | None,
) -> os.stat_result:
    if directory_descriptor is None:
        return path.stat(follow_symlinks=False)
    return os.stat(
        path.name,
        dir_fd=directory_descriptor,
        follow_symlinks=False,
    )


def _remove_created_file(
    path: Path,
    identity: _FileIdentity,
    *,
    directory_descriptor: int | None,
) -> None:
    try:
        metadata = _output_file_metadata(
            path,
            directory_descriptor=directory_descriptor,
        )
        if (
            stat.S_ISREG(metadata.st_mode)
            and not is_link_like_stat(metadata)
            and metadata.st_dev == identity.device
            and metadata.st_ino == identity.inode
        ):
            if directory_descriptor is None:
                path.unlink()
            else:
                os.unlink(path.name, dir_fd=directory_descriptor)
    except OSError:
        pass
