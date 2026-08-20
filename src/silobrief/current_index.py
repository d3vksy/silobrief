from __future__ import annotations

import os
import stat
from dataclasses import dataclass, field
from io import FileIO
from pathlib import Path

from silobrief.index import IndexData, config_digest
from silobrief.path_safety import has_link_like_component, is_link_like_stat
from silobrief.sources import (
    SourceRootIdentity,
    SourceSnapshot,
    _source_root_identity,
    load_source_config,
    snapshot_sources,
)
from silobrief.state import (
    STATE_DIRECTORY,
    ConfigData,
    _decode_object,
    _open_windows_directory,
    _open_windows_file,
    _parse_config,
)
from silobrief.stored_index import load_stored_index, parse_stored_index


class CurrentIndexError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class _FileGeneration:
    device: int
    inode: int
    size: int
    modified_time_ns: int
    changed_time_ns: int


@dataclass(frozen=True, slots=True)
class CurrentIndexApproval:
    root: Path
    root_identity: SourceRootIdentity
    index: IndexData
    config: ConfigData
    config_digest: str
    config_generation: _FileGeneration
    index_generation: _FileGeneration
    _resources: _ApprovalResources = field(repr=False, compare=False)

    def close(self) -> None:
        self._resources.close()


@dataclass(slots=True)
class _ApprovalResources:
    root: Path
    root_fd: int
    state_fd: int
    config_fd: int
    index_fd: int
    root_generation: _FileGeneration
    state_generation: _FileGeneration
    config_generation: _FileGeneration
    index_generation: _FileGeneration
    config_content: bytes
    index_content: bytes
    root_identity: SourceRootIdentity
    status: int = 0

    def revalidate(self) -> None:
        if self.status or has_link_like_component(self.root):
            raise CurrentIndexError("project settings changed during approval; run sb init")
        state = self.root / STATE_DIRECTORY
        try:
            _verify_entry(self.root, self.root.name, None, self.root_fd, self.root_generation)
            _verify_entry(
                state, STATE_DIRECTORY, self.root_fd, self.state_fd, self.state_generation
            )
            _verify_entry(
                state / "config.json",
                "config.json",
                self.state_fd,
                self.config_fd,
                self.config_generation,
            )
            _verify_entry(
                state / "index.json",
                "index.json",
                self.state_fd,
                self.index_fd,
                self.index_generation,
            )
            if (
                _read_descriptor(self.config_fd) != self.config_content
                or _read_descriptor(self.index_fd) != self.index_content
            ):
                raise CurrentIndexError("project settings changed during approval; run sb init")
        except OSError as error:
            raise CurrentIndexError(
                "project settings changed during approval; run sb init"
            ) from error

    def close(self) -> None:
        if self.status == 2:
            return
        self.status = 2
        _close_descriptors(self.root_fd, self.state_fd, self.config_fd, self.index_fd)


def load_current_index(root: Path) -> tuple[IndexData, SourceSnapshot]:
    index = load_stored_index(root)
    if index.stale:
        raise CurrentIndexError("index is stale; run sb init")

    config, root_identity = load_source_config(root)
    if index.config_digest != config_digest(config):
        raise CurrentIndexError("project configuration changed; run sb init")

    snapshot = snapshot_sources(
        root,
        config,
        expected_root_identity=root_identity,
    )
    if index.source_digest != snapshot.digest:
        raise CurrentIndexError("project sources changed; run sb init")
    return index, snapshot


def load_current_index_for_approval(
    root: Path,
) -> tuple[IndexData, SourceSnapshot, CurrentIndexApproval]:
    resolved_root = _resolve_root(root)
    load_stored_index(resolved_root)
    resources = _open_approval_resources(resolved_root)
    try:
        config = _parse_config(_decode_object("config.json", resources.config_content))
        index = parse_stored_index(resources.index_content)
        if index.stale:
            raise CurrentIndexError("index is stale; run sb init")
        if index.config_digest != config_digest(config):
            raise CurrentIndexError("project configuration changed; run sb init")
        snapshot = snapshot_sources(
            resolved_root,
            config,
            expected_root_identity=resources.root_identity,
            protected_root_descriptor=resources.root_fd,
        )
        if index.source_digest != snapshot.digest:
            raise CurrentIndexError("project sources changed; run sb init")
        resources.revalidate()
        approval = CurrentIndexApproval(
            root=resolved_root,
            root_identity=resources.root_identity,
            index=index,
            config=config,
            config_digest=index.config_digest,
            config_generation=resources.config_generation,
            index_generation=resources.index_generation,
            _resources=resources,
        )
        return index, snapshot, approval
    except BaseException:
        resources.close()
        raise


def revalidate_current_index_approval(root: Path, approval: CurrentIndexApproval) -> None:
    if approval._resources.status or _resolve_root(root) != approval.root:
        raise CurrentIndexError("project settings changed during approval; run sb init")
    approval._resources.revalidate()


def seal_current_index_approval(root: Path, approval: CurrentIndexApproval) -> None:
    revalidate_current_index_approval(root, approval)
    approval._resources.status = 1


def _open_approval_resources(root: Path) -> _ApprovalResources:
    descriptors: list[int] = []

    def hold(
        path: Path, name: str, parent: int | None, directory: bool
    ) -> tuple[int, _FileGeneration]:
        opened = _open_entry(path, name, parent, directory)
        descriptors.append(opened[0])
        return opened

    try:
        root_descriptor, root_generation = hold(root, root.name, None, True)
        state = root / STATE_DIRECTORY
        state_descriptor, state_generation = hold(state, STATE_DIRECTORY, root_descriptor, True)
        config_descriptor, config_generation = hold(
            state / "config.json", "config.json", state_descriptor, False
        )
        index_descriptor, index_generation = hold(
            state / "index.json", "index.json", state_descriptor, False
        )
        resources = _ApprovalResources(
            root=root,
            root_fd=root_descriptor,
            state_fd=state_descriptor,
            config_fd=config_descriptor,
            index_fd=index_descriptor,
            root_generation=root_generation,
            state_generation=state_generation,
            config_generation=config_generation,
            index_generation=index_generation,
            config_content=_read_descriptor(config_descriptor),
            index_content=_read_descriptor(index_descriptor),
            root_identity=_source_root_identity(root.stat(follow_symlinks=False)),
        )
        resources.revalidate()
        return resources
    except BaseException as error:
        _close_descriptors(*descriptors)
        if isinstance(error, OSError):
            raise CurrentIndexError(
                "project settings changed during approval; run sb init"
            ) from error
        raise


def _resolve_root(root: Path) -> Path:
    try:
        return root.resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise CurrentIndexError("project settings changed during approval; run sb init") from error


def _open_entry(
    path: Path,
    name: str,
    parent_descriptor: int | None,
    directory: bool,
) -> tuple[int, _FileGeneration]:
    before = _entry_stat(path, name, parent_descriptor)
    if is_link_like_stat(before) or not (
        stat.S_ISDIR(before.st_mode) if directory else stat.S_ISREG(before.st_mode)
    ):
        raise CurrentIndexError("project settings changed during approval; run sb init")
    if os.name == "nt":
        descriptor = _open_windows_directory(path) if directory else _open_windows_file(path)
    else:
        flags = os.O_RDONLY | int(getattr(os, "O_NOFOLLOW", 0))
        if directory:
            flags |= int(getattr(os, "O_DIRECTORY", 0))
        descriptor = os.open(
            name if parent_descriptor is not None else path, flags, dir_fd=parent_descriptor
        )
    try:
        opened = os.fstat(descriptor)
        after = _entry_stat(path, name, parent_descriptor)
        generation = _file_generation(opened)
        if _file_generation(before) != generation or _file_generation(after) != generation:
            raise CurrentIndexError("project settings changed during approval; run sb init")
        return descriptor, generation
    except BaseException:
        os.close(descriptor)
        raise


def _entry_stat(path: Path, name: str, parent_descriptor: int | None) -> os.stat_result:
    if os.name == "nt" or parent_descriptor is None:
        return path.stat(follow_symlinks=False)
    return os.stat(name, dir_fd=parent_descriptor, follow_symlinks=False)


def _verify_entry(
    path: Path,
    name: str,
    parent: int | None,
    descriptor: int,
    expected: _FileGeneration,
) -> None:
    if (
        _file_generation(_entry_stat(path, name, parent)) != expected
        or _file_generation(os.fstat(descriptor)) != expected
    ):
        raise CurrentIndexError("project settings changed during approval; run sb init")


def _file_generation(metadata: os.stat_result) -> _FileGeneration:
    return _FileGeneration(
        device=metadata.st_dev,
        inode=metadata.st_ino,
        size=metadata.st_size,
        modified_time_ns=metadata.st_mtime_ns,
        changed_time_ns=0 if os.name == "nt" else metadata.st_ctime_ns,
    )


def _read_descriptor(descriptor: int) -> bytes:
    position = os.lseek(descriptor, 0, os.SEEK_CUR)
    try:
        os.lseek(descriptor, 0, os.SEEK_SET)
        return FileIO(descriptor, closefd=False).read()
    finally:
        os.lseek(descriptor, position, os.SEEK_SET)


def _close_descriptors(*descriptors: int) -> None:
    for descriptor in reversed(descriptors):
        try:
            os.close(descriptor)
        except OSError:
            pass
