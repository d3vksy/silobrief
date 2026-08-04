from __future__ import annotations

from pathlib import Path

from silobrief.index import IndexData, config_digest
from silobrief.sources import SourceWarning, snapshot_sources
from silobrief.state import load_config
from silobrief.stored_index import load_stored_index


class CurrentIndexError(Exception):
    pass


def load_current_index(root: Path) -> tuple[IndexData, tuple[SourceWarning, ...]]:
    index = load_stored_index(root)
    if index.stale:
        raise CurrentIndexError("index is stale; run sb init")

    config = load_config(root)
    if index.config_digest != config_digest(config):
        raise CurrentIndexError("project configuration changed; run sb init")

    snapshot = snapshot_sources(root, config)
    if index.source_digest != snapshot.digest:
        raise CurrentIndexError("project sources changed; run sb init")
    return index, snapshot.warnings
