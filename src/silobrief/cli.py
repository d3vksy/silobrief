from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from silobrief import __version__
from silobrief.boundaries import register_boundary
from silobrief.notes import add_note
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
    ignore = subcommands.add_parser("ignore", help="Register a project boundary.")
    ignore.add_argument("path")
    ignore.add_argument("--as", dest="description", required=True)
    ignore.add_argument("--alias")
    log = subcommands.add_parser("log", help="Record public project context.")
    log.add_argument("path")
    log.add_argument("--comment", required=True)
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

    if arguments.command == "ignore":
        path_text = arguments.path
        description = arguments.description
        alias = arguments.alias
        if not isinstance(path_text, str) or not isinstance(description, str):
            parser.error("ignore path and description must be text")
        if alias is not None and not isinstance(alias, str):
            parser.error("ignore alias must be text")
        try:
            result = register_boundary(path_text, description, alias, start=Path.cwd())
        except SetupError as error:
            parser.error(str(error))
        boundary = result.boundary
        if result.changed:
            print(
                f"registered boundary {boundary['alias']} for {boundary['path']}; "
                "updated .silobrief/config.json"
            )
        else:
            print(f"boundary {boundary['alias']} for {boundary['path']} is already registered")

    if arguments.command == "log":
        path_text = arguments.path
        comment = arguments.comment
        if not isinstance(path_text, str) or not isinstance(comment, str):
            parser.error("log path and comment must be text")
        if not comment.strip():
            parser.error("note comment must not be empty")
        print(
            "warning: this comment may be included in the final brief",
            file=sys.stderr,
        )
        try:
            note = add_note(path_text, comment, start=Path.cwd())
        except SetupError as error:
            parser.error(str(error))
        print(f"recorded note {note['id']} for {note['path']}; updated .silobrief/notes.json")

    return 0
