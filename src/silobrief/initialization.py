from __future__ import annotations

from pathlib import Path

from silobrief import sources
from silobrief.index import IndexBuildError, build_index, render_index_json
from silobrief.python_structure import PythonParseError, extract_structures
from silobrief.sources import SourceChanges, SourceCollectionError, SourceWarning
from silobrief.state import SetupError, find_project_root, load_config, save_index


class IndexingError(Exception):
    pass


class SourceChangedError(Exception):
    pass


def initialize_index(start: Path) -> tuple[SourceWarning, ...]:
    root = find_project_root(start)
    config = load_config(root)
    try:
        before = sources.snapshot_sources(root, config)
        structures = extract_structures(before)
        index = build_index(before, structures, config)
        after = sources.snapshot_sources(root, config)
    except (SourceCollectionError, PythonParseError, IndexBuildError) as error:
        raise IndexingError(str(error)) from error

    changes = sources.compare_snapshots(before, after)
    if changes.has_changes:
        raise SourceChangedError(_source_change_message(changes))

    try:
        save_index(root, render_index_json(index))
    except SetupError as error:
        raise IndexingError(str(error)) from error
    return before.warnings


def _source_change_message(changes: SourceChanges) -> str:
    details: list[str] = []
    for label, paths in (
        ("added", changes.added),
        ("removed", changes.removed),
        ("modified", changes.modified),
    ):
        if paths:
            details.append(f"{label}: {', '.join(paths)}")
    return f"source changed during indexing: {'; '.join(details)}"
