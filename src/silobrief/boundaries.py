from __future__ import annotations

import importlib
import os
import stat
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Protocol, cast

from silobrief.path_safety import has_link_like_component, is_link_like
from silobrief.state import (
    BoundaryData,
    ConfigData,
    SetupError,
    find_project_root,
    is_valid_boundary_alias,
    update_config_with_stale_index,
)


@dataclass(frozen=True, slots=True)
class RegistrationResult:
    boundary: BoundaryData
    changed: bool


class _FileLockModule(Protocol):
    LOCK_EX: int
    LOCK_UN: int

    def flock(self, descriptor: int, operation: int) -> None: ...


_LOCK_RETRY_SECONDS = 0.05
_LOCK_TIMEOUT_SECONDS = 30.0


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

    def update(config: ConfigData) -> tuple[ConfigData | None, RegistrationResult]:
        boundaries = config["boundaries"]

        existing = next((item for item in boundaries if item["path"] == relative_path), None)
        if existing is not None:
            expected_alias = existing["alias"] if alias is None else alias
            if existing["description"] == description and existing["alias"] == expected_alias:
                return None, RegistrationResult(boundary=existing, changed=False)
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
        return updated, RegistrationResult(boundary=boundary, changed=True)

    return update_config_with_stale_index(root, update, lock=_config_update_lock)


def unregister_boundary(selector: str, *, start: Path) -> BoundaryData:
    if not selector.strip():
        raise SetupError("boundary selector must not be empty")

    root = find_project_root(start)

    def update(config: ConfigData) -> tuple[ConfigData | None, BoundaryData]:
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
        return updated, boundary

    return update_config_with_stale_index(root, update, lock=_config_update_lock)


@contextmanager
def _config_update_lock(state: Path, state_descriptor: int | None) -> Iterator[None]:
    if sys.platform != "win32":
        if state_descriptor is None:
            raise SetupError("state directory descriptor is unavailable")
        _lock_descriptor(state_descriptor)
        try:
            yield
        finally:
            _unlock_descriptor(state_descriptor)
        return

    path = state / ".config.lock"
    if is_link_like(path):
        raise SetupError("config lock must be a real file")
    flags = os.O_CREAT | os.O_RDWR | int(getattr(os, "O_NOFOLLOW", 0))
    try:
        descriptor = os.open(path, flags, 0o600)
    except OSError as error:
        raise SetupError(f"cannot open config lock: {error}") from error
    acquired = False
    try:
        try:
            metadata = os.fstat(descriptor)
            current = path.stat(follow_symlinks=False)
        except OSError as error:
            raise SetupError(f"cannot validate config lock: {error}") from error
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_nlink != 1
            or not os.path.samestat(metadata, current)
        ):
            raise SetupError("config lock must be a real file")
        _lock_descriptor(descriptor)
        acquired = True
        _ensure_lock_byte(descriptor)
        try:
            current = path.stat(follow_symlinks=False)
        except OSError as error:
            raise SetupError(f"cannot revalidate config lock: {error}") from error
        if is_link_like(path) or not os.path.samestat(os.fstat(descriptor), current):
            raise SetupError("config lock changed while it was acquired")
        yield
    finally:
        try:
            if acquired:
                _unlock_descriptor(descriptor)
        finally:
            os.close(descriptor)


def _ensure_lock_byte(descriptor: int) -> None:
    if os.fstat(descriptor).st_size:
        return
    try:
        position = os.lseek(descriptor, 0, os.SEEK_CUR)
        os.lseek(descriptor, 0, os.SEEK_SET)
        if os.write(descriptor, b"\0") != 1:
            raise OSError("short write while initializing the lock")
        os.lseek(descriptor, position, os.SEEK_SET)
    except OSError as error:
        raise SetupError(f"cannot initialize config lock: {error}") from error


def _lock_descriptor(descriptor: int) -> None:
    if sys.platform != "win32":
        file_locks = cast(_FileLockModule, importlib.import_module("fcntl"))

        try:
            file_locks.flock(descriptor, file_locks.LOCK_EX)
        except OSError as error:
            raise SetupError(f"cannot acquire config lock: {error}") from error
        return

    import msvcrt

    deadline = time.monotonic() + _LOCK_TIMEOUT_SECONDS
    while True:
        try:
            os.lseek(descriptor, 0, os.SEEK_SET)
            msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
            return
        except OSError as error:
            if time.monotonic() >= deadline:
                raise SetupError("timed out waiting for config lock") from error
            time.sleep(_LOCK_RETRY_SECONDS)


def _unlock_descriptor(descriptor: int) -> None:
    try:
        if sys.platform == "win32":
            import msvcrt

            os.lseek(descriptor, 0, os.SEEK_SET)
            msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
        else:
            file_locks = cast(_FileLockModule, importlib.import_module("fcntl"))

            file_locks.flock(descriptor, file_locks.LOCK_UN)
    except OSError as error:
        raise SetupError(f"cannot release config lock: {error}") from error


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
        if has_link_like_component(start):
            raise SetupError("current directory must not contain a symbolic link or reparse point")
        current = start.resolve(strict=True)
        current.relative_to(root)
    except SetupError:
        raise
    except (OSError, ValueError) as error:
        raise SetupError("current directory is outside the project root") from error

    parts = tuple(part for part in normalized.parts if part not in ("", "."))
    candidate = current
    for part in parts:
        candidate /= part
        if is_link_like(candidate):
            raise SetupError("boundary path must not contain symbolic links or reparse points")
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
