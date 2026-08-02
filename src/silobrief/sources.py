from __future__ import annotations

import hashlib
import os
import stat
from dataclasses import dataclass
from pathlib import Path

from silobrief.state import ConfigData

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
class SourceSnapshot:
    files: tuple[SourceFile, ...]
    warnings: tuple[SourceWarning, ...]
    digest: str


@dataclass(frozen=True, slots=True)
class SourceChanges:
    added: tuple[str, ...]
    removed: tuple[str, ...]
    modified: tuple[str, ...]

    @property
    def has_changes(self) -> bool:
        return bool(self.added or self.removed or self.modified)


def snapshot_sources(root: Path, config: ConfigData) -> SourceSnapshot:
    project = _validated_root(root)
    default_excludes = frozenset(item.removesuffix("/") for item in config["default_excludes"])
    boundaries = tuple(item["path"] for item in config["boundaries"])
    files: list[SourceFile] = []
    warnings: list[SourceWarning] = []

    _walk_sources(
        project,
        "",
        default_excludes=default_excludes,
        boundaries=boundaries,
        files=files,
        warnings=warnings,
    )
    files.sort(key=lambda source: source.path)
    warnings.sort(key=lambda warning: (warning.path, warning.reason))
    frozen_files = tuple(files)
    return SourceSnapshot(
        files=frozen_files,
        warnings=tuple(warnings),
        digest=_snapshot_digest(frozen_files),
    )


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


def _validated_root(root: Path) -> Path:
    if root.is_symlink() or not root.is_dir():
        raise SourceCollectionError("project root must be a real directory")
    try:
        return root.resolve(strict=True)
    except OSError as error:
        raise SourceCollectionError(
            f"cannot resolve project root: {_error_reason(error)}"
        ) from error


def _walk_sources(
    directory: Path,
    relative_directory: str,
    *,
    default_excludes: frozenset[str],
    boundaries: tuple[str, ...],
    files: list[SourceFile],
    warnings: list[SourceWarning],
) -> None:
    try:
        metadata = directory.stat(follow_symlinks=False)
    except OSError as error:
        label = relative_directory or "."
        raise SourceCollectionError(
            f"cannot inspect source directory {label}: {_error_reason(error)}"
        ) from error
    if stat.S_ISLNK(metadata.st_mode):
        warnings.append(SourceWarning(path=relative_directory, reason="symbolic link skipped"))
        return
    if not stat.S_ISDIR(metadata.st_mode):
        label = relative_directory or "."
        raise SourceCollectionError(f"source directory changed during traversal: {label}")

    try:
        with os.scandir(directory) as iterator:
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
            if entry.is_symlink():
                warnings.append(SourceWarning(path=relative_path, reason="symbolic link skipped"))
                continue
            if entry.is_dir(follow_symlinks=False):
                _walk_sources(
                    Path(entry.path),
                    relative_path,
                    default_excludes=default_excludes,
                    boundaries=boundaries,
                    files=files,
                    warnings=warnings,
                )
                continue
            if relative_path.endswith(".py") and entry.is_file(follow_symlinks=False):
                files.append(_read_regular_source(Path(entry.path), relative_path))
        except OSError as error:
            raise SourceCollectionError(
                f"cannot inspect source entry {relative_path}: {_error_reason(error)}"
            ) from error


def _is_excluded(
    relative_path: str,
    name: str,
    default_excludes: frozenset[str],
    boundaries: tuple[str, ...],
) -> bool:
    if name in default_excludes:
        return True
    return any(
        boundary == "." or relative_path == boundary or relative_path.startswith(f"{boundary}/")
        for boundary in boundaries
    )


def _read_regular_source(path: Path, relative_path: str) -> SourceFile:
    try:
        before = path.stat(follow_symlinks=False)
        if not stat.S_ISREG(before.st_mode):
            raise SourceCollectionError(f"source entry changed before read: {relative_path}")
        with path.open("rb") as stream:
            content = stream.read()
            opened = os.fstat(stream.fileno())
        after = path.stat(follow_symlinks=False)
    except SourceCollectionError:
        raise
    except OSError as error:
        raise SourceCollectionError(
            f"cannot read source file {relative_path}: {_error_reason(error)}"
        ) from error

    if not _same_file_state(before, opened) or not _same_file_state(opened, after):
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
        and left.st_dev == right.st_dev
        and left.st_ino == right.st_ino
        and left.st_size == right.st_size
        and left.st_mtime_ns == right.st_mtime_ns
    )


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
