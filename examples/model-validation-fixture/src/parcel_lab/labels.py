"""Synthetic label example. VALIDATION_MODULE_CANARY_LABELS."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class LabelOptions:
    prefix: str
    uppercase: bool = False


def format_label(reference: str, options: LabelOptions) -> str:
    label = f"{options.prefix}{reference}"
    return label.upper() if options.uppercase else label
