from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath, PureWindowsPath

from silobrief.state import (
    ConfigData,
    HumanNoteData,
    NotesData,
    SetupError,
    find_project_root,
    load_config,
    load_notes,
    save_notes,
)


def add_note(
    path_text: str,
    comment: str,
    *,
    start: Path,
) -> HumanNoteData:
    if not comment.strip():
        raise SetupError("note comment must not be empty")

    root = find_project_root(start)
    relative_path = _note_path(root, start, path_text)
    config = load_config(root)
    _require_allowed_path(relative_path, config)
    notes = load_notes(root)
    note = HumanNoteData(
        comment=comment,
        id=_note_id(len(notes["notes"]), relative_path, comment),
        path=relative_path,
    )
    updated = NotesData(notes=[*notes["notes"], note], notes_version=1)
    save_notes(root, updated)
    return note


def _note_path(root: Path, start: Path, path_text: str) -> str:
    if not path_text:
        raise SetupError("note path must not be empty")
    windows_path = PureWindowsPath(path_text)
    normalized = PurePosixPath(path_text.replace("\\", "/"))
    if normalized.is_absolute() or windows_path.drive or windows_path.root:
        raise SetupError("note path must be relative")
    if ".." in normalized.parts:
        raise SetupError("note path must not contain ..")

    try:
        current = start.resolve(strict=True)
        current.relative_to(root)
    except (OSError, ValueError) as error:
        raise SetupError("current directory is outside the project root") from error

    candidate = current
    for part in (part for part in normalized.parts if part not in ("", ".")):
        candidate /= part
        if candidate.is_symlink():
            raise SetupError("note path must not contain symbolic links")
    if not candidate.is_file() and not candidate.is_dir():
        raise SetupError("note path must be an existing file or directory")

    try:
        relative = candidate.resolve(strict=True).relative_to(root)
    except (OSError, ValueError) as error:
        raise SetupError("note path resolves outside the project root") from error
    return relative.as_posix() or "."


def _require_allowed_path(path: str, config: ConfigData) -> None:
    parts = PurePosixPath(path).parts
    excluded_names = {excluded.removesuffix("/") for excluded in config["default_excludes"]}
    if any(part in excluded_names for part in parts):
        raise SetupError("note path is excluded by the default policy")
    if any(
        boundary["path"] == "."
        or path == boundary["path"]
        or path.startswith(f"{boundary['path']}/")
        for boundary in config["boundaries"]
    ):
        raise SetupError("note path is inside a registered boundary")


def _note_id(position: int, path: str, comment: str) -> str:
    value: dict[str, object] = {
        "comment": comment,
        "path": path,
        "position": position,
    }
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return f"note-{hashlib.sha256(encoded).hexdigest()}"
