from __future__ import annotations

import os
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import TextIO

from silobrief.renderer import RenderedBrief
from silobrief.state import STATE_DIRECTORY

_APPROVAL_PROMPT = "Type exactly WRITE to create the Markdown file: "


class OutputBlockedError(Exception):
    pass


def approve_and_write(
    root: Path,
    output_text: str,
    rendered: RenderedBrief,
    *,
    start: Path,
    input_stream: TextIO,
    output_stream: TextIO,
) -> Path:
    if not input_stream.isatty() or not output_stream.isatty():
        raise OutputBlockedError("approval requires interactive input and output")
    if type(rendered) is not RenderedBrief:
        raise OutputBlockedError("output requires a rendered brief")

    destination = _output_path(root, start, output_text)
    try:
        output_stream.write(rendered.main_markdown)
        output_stream.write(f"\n{_APPROVAL_PROMPT}")
        output_stream.flush()
        approval = input_stream.readline()
    except OSError as error:
        raise OutputBlockedError(f"cannot complete interactive approval: {error}") from error
    if _without_line_ending(approval) != "WRITE":
        raise OutputBlockedError("output was not approved with exact WRITE")

    _write_new_file(destination, rendered.main_markdown)
    return destination


def _output_path(root: Path, start: Path, output_text: str) -> Path:
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

    resolved_root = _real_directory(root, "project root")
    resolved_start = _real_directory(start, "current directory")
    try:
        resolved_start.relative_to(resolved_root)
    except ValueError as error:
        raise OutputBlockedError("current directory is outside the project root") from error

    candidate = requested if requested.is_absolute() else resolved_start / requested
    candidate = candidate.absolute()
    if candidate.is_symlink():
        raise OutputBlockedError("output path must not be a symbolic link")
    if candidate.exists():
        raise OutputBlockedError("output path already exists")

    parent = _real_parent(candidate.parent)
    destination = parent / candidate.name
    if destination.is_symlink():
        raise OutputBlockedError("output path must not be a symbolic link")
    if destination.exists():
        raise OutputBlockedError("output path already exists")
    _require_allowed_location(destination, resolved_root)
    return destination


def _uses_foreign_windows_path(path: str, *, platform: str) -> bool:
    windows = PureWindowsPath(path)
    return platform != "nt" and bool(windows.drive or "\\" in path)


def _real_directory(path: Path, label: str) -> Path:
    if path.is_symlink() or not path.is_dir():
        raise OutputBlockedError(f"{label} must be a real directory")
    try:
        return path.resolve(strict=True)
    except OSError as error:
        raise OutputBlockedError(f"cannot resolve {label}: {error}") from error


def _real_parent(parent: Path) -> Path:
    current = Path(parent.anchor)
    for part in parent.parts[1:]:
        current /= part
        if current.is_symlink():
            raise OutputBlockedError("output path contains a symbolic link")
    if not parent.is_dir():
        raise OutputBlockedError("output parent must be an existing directory")
    try:
        return parent.resolve(strict=True)
    except OSError as error:
        raise OutputBlockedError(f"cannot resolve output parent: {error}") from error


def _require_allowed_location(destination: Path, root: Path) -> None:
    try:
        destination.relative_to(root)
    except ValueError:
        return

    exports = root / STATE_DIRECTORY / "exports"
    if exports.is_symlink() or not exports.is_dir():
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


def _write_new_file(path: Path, content: str) -> None:
    try:
        encoded = content.encode("utf-8")
    except UnicodeError as error:
        raise OutputBlockedError("rendered brief is not valid UTF-8 text") from error

    created = False
    try:
        with path.open("xb") as stream:
            created = True
            stream.write(encoded)
    except FileExistsError as error:
        raise OutputBlockedError("output path already exists") from error
    except OSError as error:
        if created:
            try:
                path.unlink()
            except OSError:
                pass
        raise OutputBlockedError(f"cannot create output file: {error}") from error
