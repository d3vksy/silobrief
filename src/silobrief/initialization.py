from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, TypeAlias

from silobrief import sources
from silobrief.index import IndexBuildError, build_index, render_index_json
from silobrief.python_structure import PythonParseError, extract_structures
from silobrief.sources import SourceChanges, SourceCollectionError, SourceWarning
from silobrief.state import SetupError, find_project_root, save_index


class IndexingError(Exception):
    pass


class SourceChangedError(Exception):
    pass


InitPhase: TypeAlias = Literal[
    "collecting",
    "analyzing",
    "building",
    "verifying",
    "writing",
    "complete",
]


@dataclass(frozen=True, slots=True)
class InitProgress:
    phase: InitPhase
    completed: int
    total: int
    source_files: int | None = None


InitProgressCallback: TypeAlias = Callable[[InitProgress], None]
_INIT_PHASE_COUNT = 5


def initialize_index(
    start: Path,
    *,
    progress: InitProgressCallback | None = None,
) -> tuple[SourceWarning, ...]:
    root = find_project_root(start)
    try:
        config, root_identity = sources.load_source_config(root)
        _report_progress(progress, "collecting", 0)
        before = sources.snapshot_sources(
            root,
            config,
            expected_root_identity=root_identity,
        )
        source_files = len(before.files)
        _report_progress(progress, "analyzing", 1, source_files)
        structures = extract_structures(before)
        _report_progress(progress, "building", 2, source_files)
        index = build_index(before, structures, config)
        _report_progress(progress, "verifying", 3, source_files)
        after = sources.snapshot_sources(
            root,
            config,
            expected_root_identity=root_identity,
        )
    except (SourceCollectionError, PythonParseError, IndexBuildError) as error:
        raise IndexingError(str(error)) from error

    changes = sources.compare_snapshots(before, after)
    if changes.has_changes:
        raise SourceChangedError(_source_change_message(changes))

    try:
        _report_progress(progress, "writing", 4, source_files)
        save_index(root, render_index_json(index))
    except SetupError as error:
        raise IndexingError(str(error)) from error
    _report_progress(progress, "complete", 5, source_files)
    if before.files:
        return before.warnings
    return (
        *before.warnings,
        SourceWarning(
            path=".",
            reason=(
                "no supported Python files were found; "
                "siloBrief currently supports Python projects only"
            ),
        ),
    )


def _report_progress(
    callback: InitProgressCallback | None,
    phase: InitPhase,
    completed: int,
    source_files: int | None = None,
) -> None:
    if callback is not None:
        callback(
            InitProgress(
                phase=phase,
                completed=completed,
                total=_INIT_PHASE_COUNT,
                source_files=source_files,
            )
        )


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
