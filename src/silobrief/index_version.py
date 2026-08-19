from __future__ import annotations

INDEX_VERSION = 2
_OLDEST_REBUILDABLE_INDEX_VERSION = 1


def is_current_index_version(value: object) -> bool:
    return type(value) is int and value == INDEX_VERSION


def is_rebuildable_index_version(value: object) -> bool:
    return type(value) is int and _OLDEST_REBUILDABLE_INDEX_VERSION <= value <= INDEX_VERSION
