from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from silobrief import __version__
from silobrief.boundaries import register_boundary, unregister_boundary
from silobrief.candidate_search import (
    CandidateSearchError,
    render_candidate_results,
    search_candidates,
)
from silobrief.chat_review import ChatReviewError, review_brief
from silobrief.current_index import CurrentIndexError, load_current_index
from silobrief.example_project import ExampleProjectError, create_example_project
from silobrief.initialization import IndexingError, SourceChangedError, initialize_index
from silobrief.notes import add_note
from silobrief.output import OutputBlockedError, approve_and_write
from silobrief.sources import SourceCollectionError
from silobrief.state import (
    IndexStateError,
    SetupError,
    find_project_root,
    load_notes,
    setup_project,
)
from silobrief.stored_index import StoredIndexError

_SOURCE_DISCLOSURE_WARNING = (
    "warning: non-ignored Python files are analyzed locally; source excerpts you select and "
    "approve may be exported verbatim with comments, docstrings, strings, and internal "
    "identifiers. siloBrief does not detect secrets or provide security approval; review all "
    "output yourself."
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sb",
        description="Create a reviewed research brief from Python project context.",
    )
    parser.add_argument("--version", action="version", version=f"siloBrief {__version__}")
    subcommands = parser.add_subparsers(dest="command", required=True)
    setup = subcommands.add_parser("setup", help="Initialize local project state.")
    setup.add_argument("path", nargs="?", type=Path, default=Path.cwd())
    example = subcommands.add_parser("example", help="Create a guided practice project.")
    example.add_argument("path", type=Path)
    ignore = subcommands.add_parser("ignore", help="Register a project boundary.")
    ignore.add_argument("path")
    ignore.add_argument("--as", dest="description", required=True)
    ignore.add_argument("--alias")
    unignore = subcommands.add_parser("unignore", help="Remove a registered project boundary.")
    unignore.add_argument("selector")
    subcommands.add_parser("init", help="Build the local source index.")
    log = subcommands.add_parser("log", help="Record public project context.")
    log.add_argument("path")
    log.add_argument("--comment", required=True)
    search = subcommands.add_parser("search", help="Find candidate code for a request.")
    search.add_argument("prompt")
    chat = subcommands.add_parser("chat", help="Create a reviewed research brief.")
    chat.add_argument("prompt")
    chat.add_argument("--out", dest="output", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    arguments = parser.parse_args(argv)

    if arguments.command == "example":
        project = arguments.path
        if not isinstance(project, Path):
            parser.error("example path must be a filesystem path")
        try:
            file_count = create_example_project(project)
        except ExampleProjectError as error:
            parser.error(str(error))
        print(f"created example project with {file_count} files at {project}")
        print("next: enter that directory and run sb setup .")

    if arguments.command == "setup":
        project = arguments.path
        if not isinstance(project, Path):
            parser.error("setup path must be a filesystem path")
        try:
            created = setup_project(project)
        except SetupError as error:
            parser.error(str(error))
        if created:
            print("created .silobrief/config.json, .silobrief/notes.json, and .silobrief/exports/")
        else:
            print("validated existing .silobrief state")
        print(_SOURCE_DISCLOSURE_WARNING)

    if arguments.command == "ignore":
        path_text = arguments.path
        description = arguments.description
        alias = arguments.alias
        if not isinstance(path_text, str) or not isinstance(description, str):
            parser.error("ignore path and description must be text")
        if alias is not None and not isinstance(alias, str):
            parser.error("ignore alias must be text")
        try:
            registration = register_boundary(path_text, description, alias, start=Path.cwd())
        except SetupError as error:
            parser.error(str(error))
        boundary = registration.boundary
        if registration.changed:
            print(
                f"registered boundary {boundary['alias']} for {boundary['path']}; "
                "updated .silobrief/config.json"
            )
        else:
            print(f"boundary {boundary['alias']} for {boundary['path']} is already registered")

    if arguments.command == "unignore":
        selector = arguments.selector
        if not isinstance(selector, str):
            parser.error("unignore selector must be text")
        try:
            boundary = unregister_boundary(selector, start=Path.cwd())
        except SetupError as error:
            parser.error(str(error))
        print(
            f"removed boundary {boundary['alias']} for {boundary['path']}; "
            "run sb init before sb chat"
        )

    if arguments.command == "init":
        try:
            warnings = initialize_index(Path.cwd())
        except SetupError as error:
            parser.error(str(error))
        except IndexingError as error:
            print(f"sb: error: {error}", file=sys.stderr)
            return 3
        except SourceChangedError as error:
            print(f"sb: error: {error}", file=sys.stderr)
            return 4
        for warning in warnings:
            print(f"warning: {warning.path}: {warning.reason}", file=sys.stderr)
        print("built .silobrief/index.json")

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

    if arguments.command == "search":
        prompt = arguments.prompt
        if not isinstance(prompt, str) or not prompt.strip():
            parser.error("request must not be empty")

        start = Path.cwd()
        try:
            root = find_project_root(start)
            index, snapshot = load_current_index(root)
            notes = load_notes(root)
            search_output = render_candidate_results(search_candidates(prompt, index, notes))
        except IndexStateError as error:
            print(f"sb: error: {error}", file=sys.stderr)
            return 3
        except SetupError as error:
            parser.error(str(error))
        except StoredIndexError as error:
            print(f"sb: error: {error}", file=sys.stderr)
            return 3
        except (CurrentIndexError, SourceCollectionError, CandidateSearchError) as error:
            print(f"sb: error: {error}", file=sys.stderr)
            return 4

        for warning in snapshot.warnings:
            print(f"warning: {warning.path}: {warning.reason}", file=sys.stderr)
        print(search_output, end="")

    if arguments.command == "chat":
        prompt = arguments.prompt
        output_text = arguments.output
        if not isinstance(prompt, str) or not prompt.strip():
            parser.error("request must not be empty")
        if not isinstance(output_text, str) or not output_text.strip():
            parser.error("output path must not be empty")

        start = Path.cwd()
        try:
            root = find_project_root(start)
            index, snapshot = load_current_index(root)
            notes = load_notes(root)
        except IndexStateError as error:
            print(f"sb: error: {error}", file=sys.stderr)
            return 3
        except SetupError as error:
            parser.error(str(error))
        except StoredIndexError as error:
            print(f"sb: error: {error}", file=sys.stderr)
            return 3
        except (CurrentIndexError, SourceCollectionError) as error:
            print(f"sb: error: {error}", file=sys.stderr)
            return 4

        for warning in snapshot.warnings:
            print(f"warning: {warning.path}: {warning.reason}", file=sys.stderr)
        try:
            rendered = review_brief(
                prompt,
                index,
                notes,
                input_stream=sys.stdin,
                output_stream=sys.stdout,
                snapshot=snapshot,
            )
            approve_and_write(
                root,
                output_text,
                rendered,
                start=start,
                input_stream=sys.stdin,
                output_stream=sys.stdout,
                source_snapshot=snapshot,
            )
        except (ChatReviewError, OutputBlockedError) as error:
            print(f"sb: error: {error}", file=sys.stderr)
            return 4
        print(f"\nwrote {output_text}")

    return 0
