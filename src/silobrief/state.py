from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import TypedDict

STATE_DIRECTORY = ".silobrief"
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


class _ConfigData(TypedDict):
    boundaries: list[object]
    default_excludes: list[str]
    schema_version: int


class _NotesData(TypedDict):
    notes: list[object]
    notes_version: int


def setup_project(project: Path) -> None:
    root = _project_root(project)
    state = root / STATE_DIRECTORY

    if state.exists() or state.is_symlink():
        _validate_state(state)
        return

    try:
        state.mkdir()
    except FileExistsError:
        _validate_state(state)
        return
    except OSError as error:
        raise SetupError(f"cannot create {STATE_DIRECTORY}: {error}") from error

    try:
        (state / "exports").mkdir()
        _write_json(
            state / "config.json",
            _ConfigData(
                boundaries=[],
                default_excludes=list(DEFAULT_EXCLUDES),
                schema_version=1,
            ),
        )
        _write_json(state / "notes.json", _NotesData(notes=[], notes_version=1))
    except OSError as error:
        shutil.rmtree(state, ignore_errors=True)
        raise SetupError(f"cannot initialize {STATE_DIRECTORY}: {error}") from error


def _project_root(project: Path) -> Path:
    if project.is_symlink():
        raise SetupError("project root must not be a symbolic link")
    if not project.is_dir():
        raise SetupError("project root must be an existing directory")

    try:
        return project.resolve(strict=True)
    except OSError as error:
        raise SetupError(f"cannot resolve project root: {error}") from error


def _write_json(path: Path, value: _ConfigData | _NotesData) -> None:
    content = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    path.write_text(content, encoding="utf-8", newline="\n")


def _validate_state(state: Path) -> None:
    if state.is_symlink() or not state.is_dir():
        raise SetupError(f"{STATE_DIRECTORY} must be a real directory")

    config = _read_object(state / "config.json")
    if set(config) != {"boundaries", "default_excludes", "schema_version"}:
        raise SetupError("config.json has an incompatible schema")
    if config["schema_version"] != 1:
        raise SetupError("config.json has an unsupported schema version")
    if not isinstance(config["boundaries"], list):
        raise SetupError("config.json boundaries must be an array")
    excludes = config["default_excludes"]
    if not isinstance(excludes, list) or not all(isinstance(item, str) for item in excludes):
        raise SetupError("config.json default_excludes must be a string array")
    if tuple(excludes) != DEFAULT_EXCLUDES:
        raise SetupError("config.json default exclusions do not match version 1")

    notes = _read_object(state / "notes.json")
    if set(notes) != {"notes", "notes_version"}:
        raise SetupError("notes.json has an incompatible schema")
    if notes["notes_version"] != 1 or not isinstance(notes["notes"], list):
        raise SetupError("notes.json is not compatible with version 1")

    exports = state / "exports"
    if exports.is_symlink() or not exports.is_dir():
        raise SetupError("exports must be a real directory")

    index = state / "index.json"
    if index.exists() or index.is_symlink():
        index_data = _read_object(index)
        if index_data.get("index_version") != 1:
            raise SetupError("index.json is not compatible with version 1")


def _read_object(path: Path) -> dict[str, object]:
    if path.is_symlink() or not path.is_file():
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
