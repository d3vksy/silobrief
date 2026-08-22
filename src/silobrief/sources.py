from __future__ import annotations

import hashlib
import os
import stat
import sys
from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass, field
from pathlib import Path

from silobrief.path_safety import (
    has_link_like_component,
    is_link_like_stat,
)
from silobrief.state import ConfigData, load_config

_DIGEST_DOMAIN = b"silobrief-source-snapshot-v1\0"


class SourceCollectionError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class SourceFile:
    path: str
    content: bytes
    sha256: str


@dataclass(frozen=True, slots=True)
class SourceWarning:
    path: str
    reason: str


@dataclass(frozen=True, slots=True)
class SourceRootIdentity:
    device: int
    inode: int
    change_time_ns: int


@dataclass(frozen=True, slots=True)
class SourceSnapshot:
    files: tuple[SourceFile, ...]
    warnings: tuple[SourceWarning, ...]
    digest: str
    root_identity: SourceRootIdentity | None = None


@dataclass(frozen=True, slots=True)
class SourceChanges:
    added: tuple[str, ...]
    removed: tuple[str, ...]
    modified: tuple[str, ...]

    @property
    def has_changes(self) -> bool:
        return bool(self.added or self.removed or self.modified)


@dataclass(frozen=True, slots=True)
class _SourceDirectory:
    path: Path
    expected_path: Path
    identity: SourceRootIdentity
    descriptor: int | None = None
    windows_handle: int | None = None


@dataclass(slots=True)
class _BoundaryNode:
    name: str
    relative_path: str
    final: bool = False
    children: dict[str, _BoundaryNode] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class _ProtectedBoundaryEntry:
    relative_path: str
    entry_id: int
    is_directory: bool
    final: bool
    handle: int


@dataclass(frozen=True, slots=True)
class _BoundaryProtection:
    entry_locations: dict[int, frozenset[str]]
    directory_entries: dict[tuple[str, int], dict[str, int]]


def load_source_config(
    root: Path,
    *,
    expected_root_identity: SourceRootIdentity | None = None,
    protected_root_descriptor: int | None = None,
) -> tuple[ConfigData, SourceRootIdentity]:
    with _validated_root(root, expected_root_identity, protected_root_descriptor) as project:
        config_root = (
            project.expected_path
            if project.descriptor is None
            else Path("/proc/self/fd") / str(project.descriptor)
        )
        config = load_config(config_root)
        _require_current_root(project)
        return config, project.identity


def snapshot_sources(
    root: Path,
    config: ConfigData,
    *,
    expected_root_identity: SourceRootIdentity | None = None,
    protected_root_descriptor: int | None = None,
) -> SourceSnapshot:
    default_excludes = frozenset(item.removesuffix("/") for item in config["default_excludes"])
    boundaries = tuple(item["path"] for item in config["boundaries"])
    files: list[SourceFile] = []
    warnings: list[SourceWarning] = []

    with _validated_root(root, expected_root_identity, protected_root_descriptor) as project:
        with _protected_boundary_entries(project, boundaries) as protection:
            _walk_sources(
                project,
                "",
                project=project,
                default_excludes=default_excludes,
                boundaries=boundaries,
                boundary_entry_ids=protection.entry_locations,
                boundary_directory_ids=protection.directory_entries,
                files=files,
                visible_paths=None,
                warnings=warnings,
            )
        _require_current_root(project)
        root_identity = project.identity
    files.sort(key=lambda source: source.path)
    warnings.sort(key=lambda warning: (warning.path, warning.reason))
    frozen_files = tuple(files)
    return SourceSnapshot(
        files=frozen_files,
        warnings=tuple(warnings),
        digest=_snapshot_digest(frozen_files),
        root_identity=root_identity,
    )


def list_allowed_file_paths(
    root: Path,
    config: ConfigData,
    *,
    expected_root_identity: SourceRootIdentity | None = None,
    protected_root_descriptor: int | None = None,
) -> tuple[str, ...]:
    """List regular project files without reading non-Python file contents."""
    default_excludes = frozenset(item.removesuffix("/") for item in config["default_excludes"])
    boundaries = tuple(item["path"] for item in config["boundaries"])
    python_files: list[SourceFile] = []
    visible_paths: list[str] = []
    warnings: list[SourceWarning] = []

    with _validated_root(root, expected_root_identity, protected_root_descriptor) as project:
        with _protected_boundary_entries(project, boundaries) as protection:
            _walk_sources(
                project,
                "",
                project=project,
                default_excludes=default_excludes,
                boundaries=boundaries,
                boundary_entry_ids=protection.entry_locations,
                boundary_directory_ids=protection.directory_entries,
                files=python_files,
                visible_paths=visible_paths,
                warnings=warnings,
            )
        _require_current_root(project)
    return tuple(sorted(visible_paths))


def compare_snapshots(before: SourceSnapshot, after: SourceSnapshot) -> SourceChanges:
    before_files = {source.path: source.sha256 for source in before.files}
    after_files = {source.path: source.sha256 for source in after.files}
    before_paths = set(before_files)
    after_paths = set(after_files)
    return SourceChanges(
        added=tuple(sorted(after_paths - before_paths)),
        removed=tuple(sorted(before_paths - after_paths)),
        modified=tuple(
            path
            for path in sorted(before_paths & after_paths)
            if before_files[path] != after_files[path]
        ),
    )


@contextmanager
def _validated_root(
    root: Path,
    expected_identity: SourceRootIdentity | None = None,
    protected_root_descriptor: int | None = None,
) -> Iterator[_SourceDirectory]:
    path = Path(os.path.abspath(root))
    try:
        before = path.stat(follow_symlinks=False)
        identity = _source_root_identity(before)
        if (
            not stat.S_ISDIR(before.st_mode)
            or is_link_like_stat(before)
            or has_link_like_component(path)
        ):
            raise SourceCollectionError("project root must be a real directory")
        if expected_identity is not None and identity != expected_identity:
            raise SourceCollectionError("project root changed after loading configuration")
        with _open_root_directory(path, identity, protected_root_descriptor) as directory:
            yield directory
    except SourceCollectionError:
        raise
    except OSError as error:
        raise SourceCollectionError(
            f"cannot protect project root: {_error_reason(error)}"
        ) from error


def _source_root_identity(metadata: os.stat_result) -> SourceRootIdentity:
    return SourceRootIdentity(
        int(metadata.st_dev),
        int(metadata.st_ino),
        int(metadata.st_ctime_ns),
    )


def _require_current_root(project: _SourceDirectory) -> None:
    try:
        current = project.path.stat(follow_symlinks=False)
        if (
            _source_root_identity(current) != project.identity
            or not stat.S_ISDIR(current.st_mode)
            or is_link_like_stat(current)
            or has_link_like_component(project.path)
        ):
            raise SourceCollectionError("project root changed during source collection")
    except SourceCollectionError:
        raise
    except OSError as error:
        raise SourceCollectionError("project root changed during source collection") from error


def _walk_sources(
    directory: _SourceDirectory,
    relative_directory: str,
    *,
    project: _SourceDirectory,
    default_excludes: frozenset[str],
    boundaries: tuple[str, ...],
    boundary_entry_ids: dict[int, frozenset[str]],
    boundary_directory_ids: dict[tuple[str, int], dict[str, int]],
    files: list[SourceFile],
    visible_paths: list[str] | None,
    warnings: list[SourceWarning],
) -> None:
    try:
        metadata = _directory_metadata(directory)
    except OSError as error:
        label = relative_directory or "."
        raise SourceCollectionError(
            f"cannot inspect source directory {label}: {_error_reason(error)}"
        ) from error
    if is_link_like_stat(metadata):
        warnings.append(
            SourceWarning(path=relative_directory, reason=_link_warning_reason(metadata))
        )
        return
    if not stat.S_ISDIR(metadata.st_mode):
        label = relative_directory or "."
        raise SourceCollectionError(f"source directory changed during traversal: {label}")

    try:
        entry_ids = (
            _windows_directory_entry_ids(directory.windows_handle)
            if directory.windows_handle is not None
            else None
        )
    except OSError as error:
        label = relative_directory or "."
        raise SourceCollectionError(
            f"cannot enumerate source directory {label}: {_error_reason(error)}"
        ) from error
    if entry_ids is not None:
        expected_entry_ids = boundary_directory_ids.get(
            (_normalized_windows_relative(relative_directory), metadata.st_ino)
        )
        if expected_entry_ids is not None and entry_ids != expected_entry_ids:
            label = relative_directory or "."
            raise SourceCollectionError(
                f"registered boundary parent changed before traversal: {label}"
            )
    try:
        with _scan_directory(directory) as iterator:
            entries = sorted(iterator, key=lambda entry: entry.name)
    except OSError as error:
        label = relative_directory or "."
        raise SourceCollectionError(
            f"cannot scan source directory {label}: {_error_reason(error)}"
        ) from error
    for entry in entries:
        relative_path = _join_path(relative_directory, entry.name)
        if _is_excluded(relative_path, entry.name, default_excludes, boundaries):
            continue
        try:
            entry_inode = entry.inode() if entry_ids is None else entry_ids.get(entry.name)
            if entry_inode is None or (entry_ids is not None and entry_inode == 0):
                raise OSError("source entry changed after directory enumeration")
            allowed_locations = boundary_entry_ids.get(entry_inode)
            if allowed_locations is not None and (
                _normalized_windows_relative(relative_path) not in allowed_locations
            ):
                raise SourceCollectionError(
                    f"registered boundary moved to an allowed source path: {relative_path}"
                )
            metadata = entry.stat(follow_symlinks=False)
            if is_link_like_stat(metadata):
                warnings.append(
                    SourceWarning(path=relative_path, reason=_link_warning_reason(metadata))
                )
                continue
            if stat.S_ISDIR(metadata.st_mode):
                with _open_child_directory(directory, entry.name, metadata, entry_inode) as child:
                    _walk_sources(
                        child,
                        relative_path,
                        project=project,
                        default_excludes=default_excludes,
                        boundaries=boundaries,
                        boundary_entry_ids=boundary_entry_ids,
                        boundary_directory_ids=boundary_directory_ids,
                        files=files,
                        visible_paths=visible_paths,
                        warnings=warnings,
                    )
                continue
            if stat.S_ISREG(metadata.st_mode) and visible_paths is not None:
                visible_paths.append(relative_path)
            if relative_path.endswith(".py") and stat.S_ISREG(metadata.st_mode):
                files.append(
                    _read_regular_source(
                        directory.path / entry.name,
                        relative_path,
                        project=project.expected_path,
                        parent=directory,
                        expected=metadata,
                        expected_inode=entry_inode,
                    )
                )
        except OSError as error:
            raise SourceCollectionError(
                f"cannot inspect source entry {relative_path}: {_error_reason(error)}"
            ) from error

    if entry_ids is not None:
        assert directory.windows_handle is not None
        try:
            after_entry_ids = _windows_directory_entry_ids(directory.windows_handle)
        except OSError as error:
            label = relative_directory or "."
            raise SourceCollectionError(
                f"cannot recheck source directory {label}: {_error_reason(error)}"
            ) from error
        if entry_ids != after_entry_ids:
            label = relative_directory or "."
            raise SourceCollectionError(f"source directory changed during traversal: {label}")


def _is_excluded(
    relative_path: str,
    name: str,
    default_excludes: frozenset[str],
    boundaries: tuple[str, ...],
) -> bool:
    comparison_name = os.path.normcase(name)
    if any(comparison_name == os.path.normcase(item) for item in default_excludes):
        return True
    comparison_path = os.path.normcase(relative_path)
    separator = os.path.normcase("/")
    for boundary in boundaries:
        comparison_boundary = os.path.normcase(boundary)
        if (
            comparison_boundary == "."
            or comparison_path == comparison_boundary
            or comparison_path.startswith(f"{comparison_boundary}{separator}")
        ):
            return True
    return False


@contextmanager
def _protected_boundary_entries(
    project: _SourceDirectory,
    boundaries: tuple[str, ...],
) -> Iterator[_BoundaryProtection]:
    if project.windows_handle is None:
        yield _BoundaryProtection(entry_locations={}, directory_entries={})
        return

    root = _boundary_tree(boundaries)
    if not root.children:
        yield _BoundaryProtection(entry_locations={}, directory_entries={})
        return
    handles: list[int] = []
    entries: list[_ProtectedBoundaryEntry] = []
    directory_baselines: list[tuple[str, int, int, dict[str, int]]] = []
    try:
        _capture_boundary_tree(
            project,
            root,
            project.windows_handle,
            parent_entry=None,
            handles=handles,
            entries=entries,
            directory_baselines=directory_baselines,
        )

        for relative, _, handle, expected_ids in directory_baselines:
            try:
                observed_ids = _windows_directory_entry_ids(handle)
            except OSError as error:
                label = relative or "."
                raise SourceCollectionError(
                    f"cannot recheck registered boundary parent {label}: {_error_reason(error)}"
                ) from error
            if observed_ids != expected_ids:
                label = relative or "."
                raise SourceCollectionError(
                    f"registered boundary parent changed before traversal: {label}"
                )

        for entry in entries:
            _verify_boundary_handle(
                project,
                entry.relative_path,
                entry.entry_id,
                entry.is_directory,
                entry.handle,
            )

        allowed_by_id: dict[int, set[str]] = {}
        blocked_ids: set[int] = set()
        for entry in entries:
            normalized = _normalized_windows_relative(entry.relative_path)
            if entry.final:
                blocked_ids.add(entry.entry_id)
                continue
            allowed_by_id.setdefault(entry.entry_id, set()).add(normalized)
        protected_locations = {
            entry_id: frozenset(locations) for entry_id, locations in allowed_by_id.items()
        }
        for entry_id in blocked_ids:
            protected_locations[entry_id] = frozenset()
        yield _BoundaryProtection(
            entry_locations=protected_locations,
            directory_entries={
                (_normalized_windows_relative(relative), entry_id): expected_ids
                for relative, entry_id, _, expected_ids in directory_baselines
            },
        )
    finally:
        for handle in reversed(handles):
            _close_windows_handle(handle)


def _boundary_tree(boundaries: tuple[str, ...]) -> _BoundaryNode:
    root = _BoundaryNode(name="", relative_path="")
    for boundary in sorted(set(boundaries)):
        if boundary == ".":
            root.final = True
            continue
        node = root
        for component in boundary.split("/"):
            normalized = os.path.normcase(component)
            child = node.children.get(normalized)
            if child is None:
                child = _BoundaryNode(
                    name=component,
                    relative_path=_join_path(node.relative_path, component),
                )
                node.children[normalized] = child
            node = child
        node.final = True
    return root


def _capture_boundary_tree(
    project: _SourceDirectory,
    parent: _BoundaryNode,
    parent_handle: int,
    *,
    parent_entry: _ProtectedBoundaryEntry | None,
    handles: list[int],
    entries: list[_ProtectedBoundaryEntry],
    directory_baselines: list[tuple[str, int, int, dict[str, int]]],
) -> None:
    if parent_entry is not None:
        _verify_boundary_handle(
            project,
            parent_entry.relative_path,
            parent_entry.entry_id,
            True,
            parent_entry.handle,
        )
    try:
        parent_ids = _windows_directory_entry_ids(parent_handle)
        parent_id = (
            parent_entry.entry_id
            if parent_entry is not None
            else _windows_handle_file_id(parent_handle)
        )
    except OSError as error:
        label = parent.relative_path or "."
        raise SourceCollectionError(
            f"cannot inspect registered boundary parent {label}: {_error_reason(error)}"
        ) from error
    if parent_id == 0:
        raise SourceCollectionError(
            f"registered boundary parent has no stable file ID: {parent.relative_path or '.'}"
        )
    directory_baselines.append((parent.relative_path, parent_id, parent_handle, parent_ids))
    normalized_ids: dict[str, int] = {}
    for name, entry_id in parent_ids.items():
        normalized = os.path.normcase(name)
        if normalized in normalized_ids:
            raise SourceCollectionError(
                f"registered boundary parent returned duplicate names: "
                f"{parent.relative_path or '.'}"
            )
        normalized_ids[normalized] = entry_id

    child_ids = [
        (child, normalized_ids.get(os.path.normcase(child.name)))
        for child in sorted(
            parent.children.values(),
            key=lambda item: os.path.normcase(item.name),
        )
    ]
    opened_children: list[tuple[_BoundaryNode, _ProtectedBoundaryEntry]] = []
    for child, expected_id in child_ids:
        if expected_id is None:
            continue
        if expected_id == 0:
            raise SourceCollectionError(
                f"registered boundary has no stable file ID: {child.relative_path}"
            )
        path = project.expected_path / Path(child.relative_path)
        access = 0x00000080 | (0x00000001 if child.children else 0)
        try:
            handle = _open_windows_handle(
                path,
                access,
                0x02000000 | 0x00200000,
                share=0x1 | 0x2 | 0x4,
            )
        except OSError as error:
            raise SourceCollectionError(
                f"cannot protect registered boundary {child.relative_path}: {_error_reason(error)}"
            ) from error
        handles.append(handle)
        _, is_directory = _verify_boundary_handle(
            project,
            child.relative_path,
            expected_id,
            True if child.children else None,
            handle,
        )
        entry = _ProtectedBoundaryEntry(
            relative_path=child.relative_path,
            entry_id=expected_id,
            is_directory=is_directory,
            final=child.final,
            handle=handle,
        )
        entries.append(entry)
        opened_children.append((child, entry))

    for child, entry in opened_children:
        if child.children:
            _capture_boundary_tree(
                project,
                child,
                entry.handle,
                parent_entry=entry,
                handles=handles,
                entries=entries,
                directory_baselines=directory_baselines,
            )


def _verify_boundary_handle(
    project: _SourceDirectory,
    relative: str,
    expected_id: int,
    expected_directory: bool | None,
    handle: int,
) -> tuple[int, bool]:
    expected_path = project.expected_path / Path(relative)
    try:
        attributes = _windows_handle_attributes(handle)
        actual_path = _windows_handle_path(handle)
        entry_id = _windows_handle_file_id(handle)
        observed = expected_path.stat(follow_symlinks=False)
    except OSError as error:
        raise SourceCollectionError(
            f"cannot protect registered boundary {relative}: {_error_reason(error)}"
        ) from error
    handle_directory = bool(attributes & 0x00000010)
    if (
        attributes & 0x00000400
        or (expected_directory is not None and expected_directory != handle_directory)
        or not _paths_match(expected_path, actual_path)
    ):
        raise SourceCollectionError(f"registered boundary changed before traversal: {relative}")
    if entry_id == 0:
        raise SourceCollectionError(f"registered boundary has no stable file ID: {relative}")
    if entry_id != expected_id:
        raise SourceCollectionError(f"registered boundary changed before traversal: {relative}")
    if not (
        observed.st_ino == entry_id
        and stat.S_ISDIR(observed.st_mode) == handle_directory
        and _boundary_entry_metadata(observed)
    ):
        raise SourceCollectionError(
            f"registered boundary changed while being protected: {relative}"
        )
    return entry_id, handle_directory


def _boundary_entry_metadata(metadata: os.stat_result) -> bool:
    return (
        stat.S_ISREG(metadata.st_mode) or stat.S_ISDIR(metadata.st_mode)
    ) and not is_link_like_stat(metadata)


def _read_regular_source(
    path: Path,
    relative_path: str,
    *,
    project: Path,
    parent: _SourceDirectory | None = None,
    expected: os.stat_result | None = None,
    expected_inode: int | None = None,
) -> SourceFile:
    if parent is None or expected is None or expected_inode is None:
        raise SourceCollectionError(f"source parent is not protected: {relative_path}")
    try:
        descriptor = _open_source_descriptor(parent, path.name, path)
        with os.fdopen(descriptor, "rb") as stream:
            opened = os.fstat(stream.fileno())
            opened_path = _opened_file_path(stream.fileno())
            wanted_path = project / Path(relative_path)
            if not _paths_match(wanted_path, opened_path):
                raise SourceCollectionError(
                    f"source entry changed location before read: {relative_path}"
                )
            locked_path_state = (
                (parent.expected_path / path.name).stat(follow_symlinks=False)
                if os.name == "nt"
                else opened
            )
            if not _same_file_state(locked_path_state, opened) or not _same_entry_observation(
                expected,
                locked_path_state,
                expected_inode,
                True,
            ):
                raise SourceCollectionError(f"source entry changed before read: {relative_path}")
            content = stream.read()
            after = os.fstat(stream.fileno())
            after_path = _opened_file_path(stream.fileno())
    except SourceCollectionError:
        raise
    except OSError as error:
        raise SourceCollectionError(
            f"cannot read source file {relative_path}: {_error_reason(error)}"
        ) from error

    if not _same_file_state(opened, after) or not _paths_match(opened_path, after_path):
        raise SourceCollectionError(f"source file changed while being read: {relative_path}")
    return SourceFile(
        path=relative_path,
        content=content,
        sha256=hashlib.sha256(content).hexdigest(),
    )


def _same_file_state(left: os.stat_result, right: os.stat_result) -> bool:
    return (
        stat.S_ISREG(left.st_mode)
        and stat.S_ISREG(right.st_mode)
        and not is_link_like_stat(left)
        and not is_link_like_stat(right)
        and left.st_dev == right.st_dev
        and left.st_ino == right.st_ino
        and left.st_size == right.st_size
        and left.st_mtime_ns == right.st_mtime_ns
    )


def _same_entry_observation(
    left: os.stat_result,
    right: os.stat_result,
    expected_inode: int,
    compare_file_state: bool,
) -> bool:
    same_type = stat.S_IFMT(left.st_mode) == stat.S_IFMT(right.st_mode)
    known_inode = expected_inode or left.st_ino
    same_identity = not known_inode or (
        known_inode == right.st_ino and (not left.st_dev or left.st_dev == right.st_dev)
    )
    same_state = left.st_size == right.st_size and left.st_mtime_ns == right.st_mtime_ns
    return same_type and same_identity and (not compare_file_state or same_state)


def _scan_directory(
    directory: _SourceDirectory,
) -> AbstractContextManager[Iterator[os.DirEntry[str]]]:
    target: int | Path = (
        directory.descriptor if directory.descriptor is not None else directory.expected_path
    )
    return os.scandir(target)


def _directory_metadata(directory: _SourceDirectory) -> os.stat_result:
    if directory.descriptor is not None:
        return os.fstat(directory.descriptor)
    return directory.expected_path.stat(follow_symlinks=False)


@contextmanager
def _open_root_directory(
    path: Path,
    expected_identity: SourceRootIdentity,
    protected_root_descriptor: int | None = None,
) -> Iterator[_SourceDirectory]:
    if sys.platform == "win32":
        import msvcrt

        handles: list[int] = []
        borrowed_descriptor: int | None = None
        requested = Path(path.anchor)
        canonical: Path | None = None
        try:
            for component in (path.anchor, *path.parts[1:]):
                if component != path.anchor:
                    requested /= component
                current = requested if canonical is None else canonical / component
                if requested == path and protected_root_descriptor is not None:
                    borrowed_descriptor = os.dup(protected_root_descriptor)
                    handle = msvcrt.get_osfhandle(borrowed_descriptor)
                else:
                    handle = _open_windows_directory(
                        current,
                        lock_delete=requested == path,
                        list_entries=requested == path,
                    )
                    handles.append(handle)
                actual = _windows_handle_path(handle)
                if not (_paths_match(current, actual) or os.path.samefile(current, actual)):
                    raise OSError("project root component changed while opening")
                canonical = actual
            opened = path.stat(follow_symlinks=False)
            if _source_root_identity(opened) != expected_identity:
                raise OSError("project root changed while opening")
            yield _SourceDirectory(
                path=path,
                expected_path=actual,
                identity=expected_identity,
                windows_handle=handle,
            )
        finally:
            if borrowed_descriptor is not None:
                os.close(borrowed_descriptor)
            for handle in reversed(handles):
                _close_windows_handle(handle)
        return

    descriptor = (
        os.dup(protected_root_descriptor)
        if protected_root_descriptor is not None
        else _open_posix_directory_path(path)
    )
    try:
        actual = _opened_file_path(descriptor)
        opened = os.fstat(descriptor)
        if not _paths_match(path, actual) or _source_root_identity(opened) != expected_identity:
            raise OSError("project root changed while opening")
        yield _SourceDirectory(
            path=path,
            expected_path=actual,
            identity=expected_identity,
            descriptor=descriptor,
        )
    finally:
        os.close(descriptor)


@contextmanager
def _open_child_directory(
    parent: _SourceDirectory,
    name: str,
    expected: os.stat_result,
    expected_inode: int,
) -> Iterator[_SourceDirectory]:
    path = parent.path / name
    wanted_path = parent.expected_path / name
    if parent.descriptor is not None:
        descriptor = os.open(name, _directory_open_flags(), dir_fd=parent.descriptor)
        try:
            opened = os.fstat(descriptor)
            actual = _opened_file_path(descriptor)
            if not _same_entry_observation(
                expected, opened, expected_inode, False
            ) or not _paths_match(wanted_path, actual):
                raise OSError("source directory changed while opening")
            yield _SourceDirectory(
                path=path,
                expected_path=actual,
                identity=_source_root_identity(opened),
                descriptor=descriptor,
            )
        finally:
            os.close(descriptor)
        return

    handle = _open_windows_directory(wanted_path)
    try:
        actual = _windows_handle_path(handle)
        after_open = wanted_path.stat(follow_symlinks=False)
        if not _same_entry_observation(
            expected, after_open, expected_inode, False
        ) or not _paths_match(wanted_path, actual):
            raise OSError("source directory changed while opening")
        yield _SourceDirectory(
            path=path,
            expected_path=actual,
            identity=_source_root_identity(after_open),
            windows_handle=handle,
        )
    finally:
        _close_windows_handle(handle)


def _open_posix_directory_path(path: Path) -> int:
    descriptor = os.open(path.anchor, _directory_open_flags())
    try:
        for component in path.parts[1:]:
            child = os.open(component, _directory_open_flags(), dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _directory_open_flags() -> int:
    return (
        os.O_RDONLY
        | int(getattr(os, "O_CLOEXEC", 0))
        | int(getattr(os, "O_DIRECTORY", 0))
        | int(getattr(os, "O_NOFOLLOW", 0))
    )


def _open_source_descriptor(parent: _SourceDirectory, name: str, path: Path) -> int:
    if parent.descriptor is not None:
        flags = os.O_RDONLY | int(getattr(os, "O_CLOEXEC", 0))
        flags |= int(getattr(os, "O_NOFOLLOW", 0))
        return os.open(name, flags, dir_fd=parent.descriptor)
    return _open_windows_source(parent.expected_path / name)


def _opened_file_path(file_descriptor: int) -> Path:
    if os.name == "nt":
        return _windows_opened_file_path(file_descriptor)
    descriptor_path = Path("/proc/self/fd") / str(file_descriptor)
    try:
        target = os.readlink(descriptor_path)
    except OSError as error:
        raise OSError("cannot resolve opened source handle") from error
    if target.endswith(" (deleted)"):
        raise OSError("opened source file was deleted")
    opened_path = Path(target)
    if not opened_path.is_absolute():
        raise OSError("opened source handle returned a relative path")
    return opened_path


def _open_windows_directory(
    path: Path,
    *,
    lock_delete: bool = True,
    list_entries: bool = True,
) -> int:
    cwd_outside = not _windows_directory_contains_cwd(path)
    access = 0x00010080 if lock_delete and cwd_outside else 0x00000080
    if list_entries:
        access |= 0x00000001
    handle = _open_windows_handle(path, access, 0x02000000 | 0x00200000)
    try:
        attributes = _windows_handle_attributes(handle)
    except BaseException:
        _close_windows_handle(handle)
        raise
    if not attributes & 0x00000010 or attributes & 0x00000400:
        _close_windows_handle(handle)
        raise OSError("source directory is a reparse point or not a directory")
    return handle


def _windows_directory_contains_cwd(path: Path) -> bool:
    cwd = Path.cwd()
    if cwd.is_relative_to(path):
        return True
    for candidate in (cwd, *cwd.parents):
        try:
            if os.path.samefile(candidate, path):
                return True
        except OSError:
            continue
    return False


def _open_windows_source(path: Path) -> int:
    if sys.platform != "win32":
        raise OSError("Windows source handles are unavailable")
    import msvcrt

    handle = _open_windows_handle(path, 0x80010000, 0x00200000 | 0x08000000)
    try:
        attributes = _windows_handle_attributes(handle)
    except BaseException:
        _close_windows_handle(handle)
        raise
    if attributes & (0x00000010 | 0x00000400):
        _close_windows_handle(handle)
        raise OSError("source entry is a reparse point or directory")
    try:
        return msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
    except BaseException:
        _close_windows_handle(handle)
        raise


def _open_windows_handle(
    path: Path,
    access: int,
    flags: int,
    *,
    share: int = 0x1 | 0x2,
) -> int:
    if sys.platform != "win32":
        raise OSError("Windows source handles are unavailable")
    import ctypes

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
    handle = create_file(_windows_extended_path(path), access, share, None, 3, flags, None)
    invalid_handle = ctypes.c_void_p(-1).value
    if handle is None or handle == invalid_handle:
        raise OSError(ctypes.get_last_error(), "cannot open protected source path")
    return int(handle)


def _windows_directory_entry_ids(handle: int) -> dict[str, int]:
    if sys.platform != "win32":
        raise OSError("Windows source handles are unavailable")
    import ctypes

    class FileIdBothDirectoryInfo(ctypes.Structure):
        _fields_ = (
            ("next_entry_offset", ctypes.c_uint32),
            ("file_index", ctypes.c_uint32),
            ("creation_time", ctypes.c_int64),
            ("last_access_time", ctypes.c_int64),
            ("last_write_time", ctypes.c_int64),
            ("change_time", ctypes.c_int64),
            ("end_of_file", ctypes.c_int64),
            ("allocation_size", ctypes.c_int64),
            ("file_attributes", ctypes.c_uint32),
            ("file_name_length", ctypes.c_uint32),
            ("ea_size", ctypes.c_uint32),
            ("short_name_length", ctypes.c_byte),
            ("short_name", ctypes.c_wchar * 12),
            ("file_id", ctypes.c_uint64),
            ("file_name", ctypes.c_wchar * 1),
        )

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    get_info = kernel32.GetFileInformationByHandleEx
    get_info.argtypes = (ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32)
    get_info.restype = ctypes.c_int
    buffer = ctypes.create_string_buffer(65536)
    entries: dict[str, int] = {}
    information_class = 11  # FileIdBothDirectoryRestartInfo
    while True:
        if not get_info(
            ctypes.c_void_p(handle),
            information_class,
            buffer,
            len(buffer),
        ):
            error_code = ctypes.get_last_error()
            if error_code == 18:  # ERROR_NO_MORE_FILES
                return entries
            raise OSError(error_code, "cannot enumerate protected source directory")
        information_class = 10  # FileIdBothDirectoryInfo
        offset = 0
        while True:
            if offset + ctypes.sizeof(FileIdBothDirectoryInfo) > len(buffer):
                raise OSError("source directory returned truncated entry metadata")
            info = FileIdBothDirectoryInfo.from_buffer(buffer, offset)
            name_start = offset + FileIdBothDirectoryInfo.file_name.offset
            name_end = name_start + info.file_name_length
            if name_end > len(buffer) or info.file_name_length % 2:
                raise OSError("source directory returned invalid entry metadata")
            name = buffer.raw[name_start:name_end].decode("utf-16-le", errors="surrogatepass")
            if name not in (".", ".."):
                if name in entries:
                    raise OSError("source directory returned duplicate entries")
                entries[name] = int(info.file_id)
            if not info.next_entry_offset:
                break
            offset += info.next_entry_offset
            if offset >= len(buffer) or offset % 8:
                raise OSError("source directory returned invalid entry offsets")


def _windows_handle_attributes(handle: int) -> int:
    if sys.platform != "win32":
        raise OSError("Windows source handles are unavailable")
    import ctypes

    class FileAttributeTagInfo(ctypes.Structure):
        _fields_ = (("attributes", ctypes.c_uint32), ("reparse_tag", ctypes.c_uint32))

    info = FileAttributeTagInfo()
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    get_info = kernel32.GetFileInformationByHandleEx
    get_info.argtypes = (ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32)
    get_info.restype = ctypes.c_int
    if not get_info(ctypes.c_void_p(handle), 9, ctypes.byref(info), ctypes.sizeof(info)):
        raise OSError(ctypes.get_last_error(), "cannot inspect protected source path")
    return int(info.attributes)


def _windows_handle_file_id(handle: int) -> int:
    if sys.platform != "win32":
        raise OSError("Windows source handles are unavailable")
    import ctypes

    class ByHandleFileInformation(ctypes.Structure):
        _fields_ = (
            ("file_attributes", ctypes.c_uint32),
            ("creation_time_low", ctypes.c_uint32),
            ("creation_time_high", ctypes.c_uint32),
            ("last_access_time_low", ctypes.c_uint32),
            ("last_access_time_high", ctypes.c_uint32),
            ("last_write_time_low", ctypes.c_uint32),
            ("last_write_time_high", ctypes.c_uint32),
            ("volume_serial_number", ctypes.c_uint32),
            ("file_size_high", ctypes.c_uint32),
            ("file_size_low", ctypes.c_uint32),
            ("number_of_links", ctypes.c_uint32),
            ("file_index_high", ctypes.c_uint32),
            ("file_index_low", ctypes.c_uint32),
        )

    info = ByHandleFileInformation()
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    get_info = kernel32.GetFileInformationByHandle
    get_info.argtypes = (ctypes.c_void_p, ctypes.POINTER(ByHandleFileInformation))
    get_info.restype = ctypes.c_int
    if not get_info(ctypes.c_void_p(handle), ctypes.byref(info)):
        raise OSError(ctypes.get_last_error(), "cannot identify protected boundary")
    return int(info.file_index_high) << 32 | int(info.file_index_low)


def _windows_handle_path(handle: int) -> Path:
    if sys.platform != "win32":
        raise OSError("Windows source handles are unavailable")
    import ctypes

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
    length = final_path(
        ctypes.c_void_p(handle),
        buffer,
        len(buffer),
        0,
    )
    if length == 0 or length >= len(buffer):
        error_code = ctypes.get_last_error()
        raise OSError(error_code, "cannot resolve opened source file")
    value = buffer.value
    if value.startswith("\\\\?\\UNC\\"):
        value = f"\\\\{value[8:]}"
    elif value.startswith("\\\\?\\"):
        value = value[4:]
    return Path(value)


def _windows_opened_file_path(file_descriptor: int) -> Path:
    if sys.platform != "win32":
        raise OSError("Windows source handles are unavailable")
    import msvcrt

    return _windows_handle_path(msvcrt.get_osfhandle(file_descriptor))


def _windows_extended_path(path: Path) -> str:
    value = str(path)
    if value.startswith("\\\\?\\"):
        return value
    if value.startswith("\\\\"):
        return f"\\\\?\\UNC\\{value[2:]}"
    return f"\\\\?\\{value}"


def _normalized_windows_relative(path: str) -> str:
    return os.path.normcase(os.path.normpath(path))


def _close_windows_handle(handle: int) -> None:
    if sys.platform != "win32":
        raise OSError("Windows source handles are unavailable")
    import ctypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = (ctypes.c_void_p,)
    close_handle.restype = ctypes.c_int
    close_handle(ctypes.c_void_p(handle))


def _paths_match(left: Path, right: Path) -> bool:
    return _comparison_path(left) == _comparison_path(right)


def _comparison_path(path: Path) -> str:
    value = str(path)
    if os.name == "nt":
        if value[:8].lower() == "\\\\?\\unc\\":
            value = f"\\\\{value[8:]}"
        elif value.startswith("\\\\?\\"):
            value = value[4:]
    return os.path.normcase(os.path.normpath(value))


def _link_warning_reason(metadata: os.stat_result) -> str:
    return "symbolic link skipped" if stat.S_ISLNK(metadata.st_mode) else "reparse point skipped"


def _snapshot_digest(files: tuple[SourceFile, ...]) -> str:
    digest = hashlib.sha256(_DIGEST_DOMAIN)
    for source in files:
        path_bytes = source.path.encode("utf-8")
        digest.update(len(path_bytes).to_bytes(8, byteorder="big"))
        digest.update(path_bytes)
        digest.update(bytes.fromhex(source.sha256))
    return digest.hexdigest()


def _join_path(parent: str, name: str) -> str:
    return f"{parent}/{name}" if parent else name


def _error_reason(error: OSError) -> str:
    return error.strerror or type(error).__name__
