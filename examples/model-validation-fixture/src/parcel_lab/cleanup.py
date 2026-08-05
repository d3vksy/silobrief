"""Synthetic compatibility example. VALIDATION_MODULE_CANARY_CLEANUP."""

from __future__ import annotations


def choose_reference(primary: str | None, legacy: str | None) -> str:
    if primary is not None and primary.strip():
        return primary.strip()
    if legacy is not None and legacy.strip():
        return legacy.strip()
    raise ValueError("a tracking reference is required")
