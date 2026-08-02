from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from silobrief import __version__
from silobrief.state import SetupError, setup_project


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sb",
        description="Create a reviewed research brief from Python project context.",
    )
    parser.add_argument("--version", action="version", version=f"siloBrief {__version__}")
    subcommands = parser.add_subparsers(dest="command")
    setup = subcommands.add_parser("setup", help="Initialize local project state.")
    setup.add_argument("path", nargs="?", type=Path, default=Path.cwd())
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    arguments = parser.parse_args(argv)

    if arguments.command == "setup":
        project = arguments.path
        if not isinstance(project, Path):
            parser.error("setup path must be a filesystem path")
        try:
            setup_project(project)
        except SetupError as error:
            parser.error(str(error))

    return 0
