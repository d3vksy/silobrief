from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath

from silobrief.state import (
    STATE_DIRECTORY,
    BoundaryData,
    ConfigData,
    SetupError,
    find_project_root,
    is_valid_boundary_alias,
    load_config,
    mark_index_stale,
    save_config,
)


@dataclass(frozen=True, slots=True)
class RegistrationResult:
    boundary: BoundaryData
    changed: bool


@dataclass(frozen=True, slots=True)
class _FileSnapshot:
    path: Path
    content: bytes
    access_time_ns: int
    modified_time_ns: int
    mode: int


def register_boundary(
    path_text: str,
    description: str,
    alias: str | None,
    *,
    start: Path,
) -> RegistrationResult:
    if not description.strip():
        raise SetupError("boundary description must not be empty")
    if alias is not None and not is_valid_boundary_alias(alias):
        raise SetupError("boundary alias must match [a-z0-9-]{1,40}")

    root = find_project_root(start)
    relative_path = _boundary_path(root, start, path_text)
    config = load_config(root)
    boundaries = config["boundaries"]

    existing = next((item for item in boundaries if item["path"] == relative_path), None)
    if existing is not None:
        expected_alias = existing["alias"] if alias is None else alias
        if existing["description"] == description and existing["alias"] == expected_alias:
            return RegistrationResult(boundary=existing, changed=False)
        raise SetupError("boundary path is already registered with different values")

    assigned_alias = alias or _automatic_alias(boundaries)
    if any(item["alias"] == assigned_alias for item in boundaries):
        raise SetupError("boundary alias is already registered")

    boundary = BoundaryData(
        alias=assigned_alias,
        description=description,
        path=relative_path,
    )
    updated = ConfigData(
        boundaries=[*boundaries, boundary],
        default_excludes=list(config["default_excludes"]),
        schema_version=1,
    )
    _save_config_with_stale_index(root, updated)
    return RegistrationResult(boundary=boundary, changed=True)


def unregister_boundary(selector: str, *, start: Path) -> BoundaryData:
    if not selector.strip():
        raise SetupError("boundary selector must not be empty")

    root = find_project_root(start)
    config = load_config(root)
    boundaries = config["boundaries"]
    matches = [
        boundary
        for boundary in boundaries
        if selector == boundary["path"] or selector == boundary["alias"]
    ]
    if not matches:
        raise SetupError("boundary selector is not registered")
    if len(matches) > 1:
        raise SetupError("boundary selector matches more than one registered boundary")

    boundary = matches[0]
    updated = ConfigData(
        boundaries=[item for item in boundaries if item != boundary],
        default_excludes=list(config["default_excludes"]),
        schema_version=1,
    )
    _save_config_with_stale_index(root, updated)
    return boundary


def _save_config_with_stale_index(root: Path, config: ConfigData) -> None:
    index_snapshot = _snapshot_index(root)
    try:
        mark_index_stale(root)
        save_config(root, config)
    except SetupError:
        _restore_snapshot(index_snapshot)
        raise


def _boundary_path(root: Path, start: Path, path_text: str) -> str:
    if not path_text:
        raise SetupError("boundary path must not be empty")
    windows_path = PureWindowsPath(path_text)
    normalized = PurePosixPath(path_text.replace("\\", "/"))
    if normalized.is_absolute() or windows_path.drive or windows_path.root:
        raise SetupError("boundary path must be relative")
    if ".." in normalized.parts:
        raise SetupError("boundary path must not contain ..")

    try:
        current = start.resolve(strict=True)
        current.relative_to(root)
    except (OSError, ValueError) as error:
        raise SetupError("current directory is outside the project root") from error

    parts = tuple(part for part in normalized.parts if part not in ("", "."))
    candidate = current
    for part in parts:
        candidate /= part
        if candidate.is_symlink():
            raise SetupError("boundary path must not contain symbolic links")
    if not candidate.is_file() and not candidate.is_dir():
        raise SetupError("boundary path must be an existing file or directory")

    try:
        relative = candidate.resolve(strict=True).relative_to(root)
    except (OSError, ValueError) as error:
        raise SetupError("boundary path resolves outside the project root") from error
    return relative.as_posix() or "."


def _automatic_alias(boundaries: list[BoundaryData]) -> str:
    aliases = {item["alias"] for item in boundaries}
    number = len(boundaries) + 1
    while f"boundary-{number}" in aliases:
        number += 1
    return f"boundary-{number}"


def _snapshot_index(root: Path) -> _FileSnapshot | None:
    path = root / STATE_DIRECTORY / "index.json"
    if not path.is_file():
        return None
    content = path.read_bytes()
    metadata = path.stat()
    return _FileSnapshot(
        path=path,
        content=content,
        access_time_ns=metadata.st_atime_ns,
        modified_time_ns=metadata.st_mtime_ns,
        mode=stat.S_IMODE(metadata.st_mode),
    )


def _restore_snapshot(snapshot: _FileSnapshot | None) -> None:
    if snapshot is None:
        return
    current = snapshot.path.read_bytes()
    metadata = snapshot.path.stat()
    if current == snapshot.content and metadata.st_mtime_ns == snapshot.modified_time_ns:
        return
    try:
        snapshot.path.write_bytes(snapshot.content)
        os.chmod(snapshot.path, snapshot.mode)
        os.utime(
            snapshot.path,
            ns=(snapshot.access_time_ns, snapshot.modified_time_ns),
        )
    except OSError as error:
        raise SetupError(f"cannot restore {snapshot.path.name}: {error}") from error
