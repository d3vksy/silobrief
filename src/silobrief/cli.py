from __future__ import annotations

import argparse
from collections.abc import Sequence

from silobrief import __version__


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sb",
        description="Create a reviewed research brief from Python project context.",
    )
    parser.add_argument("--version", action="version", version=f"siloBrief {__version__}")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    _build_parser().parse_args(argv)
    return 0
