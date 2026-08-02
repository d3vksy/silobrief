from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath

from silobrief.state import (
    BoundaryData,
    ConfigData,
    SetupError,
    find_project_root,
    load_config,
    mark_index_stale,
    save_config,
)

_ALIAS_PATTERN = re.compile(r"[a-z0-9-]{1,40}")


@dataclass(frozen=True, slots=True)
class RegistrationResult:
    boundary: BoundaryData
    changed: bool


def register_boundary(
    path_text: str,
    description: str,
    alias: str | None,
    *,
    start: Path,
) -> RegistrationResult:
    if not description.strip():
        raise SetupError("boundary description must not be empty")
    if alias is not None and _ALIAS_PATTERN.fullmatch(alias) is None:
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
    mark_index_stale(root)
    save_config(root, updated)
    return RegistrationResult(boundary=boundary, changed=True)


def _boundary_path(root: Path, start: Path, path_text: str) -> str:
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
