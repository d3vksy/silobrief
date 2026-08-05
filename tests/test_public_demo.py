from __future__ import annotations

import contextlib
import hashlib
import io
import os
import shutil
import socket
import sys
import tempfile
import unittest
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import cast
from unittest import mock

import silobrief.sources as sources
from silobrief.cli import main

FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "examples" / "parcel-sync-fixture"
OUTPUT_PATH = ".silobrief/exports/retry-brief.md"
SOURCE_OUTPUT_PATH = ".silobrief/exports/retry-brief.sources.md"
REVIEW_INPUT = "y\n1\n\n\ny\ny\ny\ny\ny\ny\nEXPOSE\nWRITE\n"
INDEX_SHA256 = "0b810f442ca84d26de891dd08e2b77ec0c645e1753943bf8643a7f3b4dc4185e"
BRIEF_SHA256 = "a94d5b4f75954be4f72d02752002c8571558fd34953a7a05e24c828edd1c1731"
SOURCE_BRIEF_SHA256 = "3035173c36872cb7853ec590bc9acb59b69adff63ad23eee446c6b3b86a66d88"
PUBLIC_CANARIES = (
    "PUBLIC_SOURCE_BODY_CANARY",
    "PUBLIC_COMMENT_CANARY",
    "PUBLIC_DOCSTRING_CANARY",
    "PUBLIC_STRING_CANARY",
)
STRICT_PRIVATE_VALUES = (
    "PRIVATE_BOUNDARY_CANARY",
    "private_adapter",
)


class TtyOutput(io.StringIO):
    def isatty(self) -> bool:
        return True


class ScriptedInput:
    def __init__(self, value: str, target: Path) -> None:
        self._stream = io.StringIO(value)
        self.target = target
        self.source_target = target.with_name(f"{target.stem}.sources.md")
        self.output_absent_before_write: bool | None = None
        self.source_output_absent_before_write: bool | None = None

    def isatty(self) -> bool:
        return True

    def readline(self, size: int = -1) -> str:
        value = self._stream.readline(size)
        if value.rstrip("\r\n") == "WRITE":
            self.output_absent_before_write = not self.target.exists()
            self.source_output_absent_before_write = not self.source_target.exists()
        return value


@dataclass(frozen=True, slots=True)
class DemoResult:
    root: str
    source_before: tuple[tuple[str, str], ...]
    source_after: tuple[tuple[str, str], ...]
    scanned_directories: tuple[str, ...]
    opened_sources: tuple[str, ...]
    index: bytes
    brief: bytes
    source_brief: bytes
    terminal: str
    output_absent_before_write: bool | None
    source_output_absent_before_write: bool | None


@contextlib.contextmanager
def working_directory(path: Path) -> Iterator[None]:
    previous = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous)


def source_manifest(root: Path) -> tuple[tuple[str, str], ...]:
    entries: list[tuple[str, str]] = []
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if path.is_file() and ".silobrief" not in relative.parts:
            entries.append((relative.as_posix(), hashlib.sha256(path.read_bytes()).hexdigest()))
    return tuple(entries)


def run_demo(project: Path) -> DemoResult:
    shutil.copytree(FIXTURE_ROOT, project)
    before = source_manifest(project)
    input_stream = ScriptedInput(REVIEW_INPUT, project / OUTPUT_PATH)
    stdout = TtyOutput()
    stderr = io.StringIO()

    with (
        mock.patch.object(socket, "socket") as socket_constructor,
        mock.patch.object(socket, "create_connection") as create_connection,
        mock.patch.object(
            sources,
            "_read_regular_source",
            wraps=sources._read_regular_source,
        ) as read_source,
        mock.patch("silobrief.sources.os.scandir", wraps=os.scandir) as scan_directory,
        mock.patch.object(sys, "stdin", input_stream),
        contextlib.redirect_stdout(stdout),
        contextlib.redirect_stderr(stderr),
    ):
        setup_result = main(["setup", str(project)])
        with working_directory(project):
            ignore_result = main(
                [
                    "ignore",
                    "private_adapter",
                    "--as",
                    "External delivery adapter",
                    "--alias",
                    "delivery-boundary",
                ]
            )
            init_result = main(["init"])
            log_result = main(
                [
                    "log",
                    "src/parcel_sync/service.py",
                    "--comment",
                    "HTTP 503 responses may be retried.",
                ]
            )
            stdout.seek(0)
            stdout.truncate(0)
            stderr.seek(0)
            stderr.truncate(0)
            chat_result = main(["chat", "retry request", "--out", OUTPUT_PATH])
            results = (ignore_result, init_result, log_result, chat_result)

    if (setup_result, *results) != (0, 0, 0, 0, 0):
        raise AssertionError(f"public demo failed: {(setup_result, *results)}\n{stderr.getvalue()}")
    socket_constructor.assert_not_called()
    create_connection.assert_not_called()

    resolved_project = project.resolve()
    scanned = tuple(
        sorted(
            {
                Path(cast(str | os.PathLike[str], call.args[0]))
                .resolve()
                .relative_to(resolved_project)
                .as_posix()
                or "."
                for call in scan_directory.call_args_list
            }
        )
    )
    opened = tuple(sorted({cast(str, call.args[1]) for call in read_source.call_args_list}))
    return DemoResult(
        root=str(project.resolve()),
        source_before=before,
        source_after=source_manifest(project),
        scanned_directories=scanned,
        opened_sources=opened,
        index=(project / ".silobrief/index.json").read_bytes(),
        brief=(project / OUTPUT_PATH).read_bytes(),
        source_brief=(project / SOURCE_OUTPUT_PATH).read_bytes(),
        terminal=stdout.getvalue() + stderr.getvalue(),
        output_absent_before_write=input_stream.output_absent_before_write,
        source_output_absent_before_write=input_stream.source_output_absent_before_write,
    )


class PublicDemoTests(unittest.TestCase):
    def test_public_fixture_is_deterministic_offline_and_boundary_safe(self) -> None:
        self.assertTrue(FIXTURE_ROOT.is_dir(), f"public fixture is missing: {FIXTURE_ROOT}")

        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            first = run_demo(temporary / "first-project")
            second = run_demo(temporary / "second-project")

        self.assertEqual(first.source_before, first.source_after)
        self.assertEqual(second.source_before, second.source_after)
        self.assertIs(first.output_absent_before_write, True)
        self.assertIs(second.output_absent_before_write, True)
        self.assertIs(first.source_output_absent_before_write, True)
        self.assertIs(second.source_output_absent_before_write, True)
        self.assertEqual(first.index, second.index)
        self.assertEqual(first.brief, second.brief)
        self.assertEqual(first.source_brief, second.source_brief)
        self.assertEqual(hashlib.sha256(first.index).hexdigest(), INDEX_SHA256)
        self.assertEqual(hashlib.sha256(first.brief).hexdigest(), BRIEF_SHA256)
        self.assertEqual(hashlib.sha256(first.source_brief).hexdigest(), SOURCE_BRIEF_SHA256)
        self.assertEqual(
            first.scanned_directories,
            (".", "src", "src/parcel_sync"),
        )
        self.assertEqual(first.scanned_directories, second.scanned_directories)
        self.assertEqual(
            first.opened_sources,
            (
                "src/parcel_sync/__init__.py",
                "src/parcel_sync/models.py",
                "src/parcel_sync/service.py",
            ),
        )
        self.assertEqual(first.opened_sources, second.opened_sources)

        brief_text = first.brief.decode("utf-8")
        source_brief_text = first.source_brief.decode("utf-8")
        for expected in (
            "src/parcel_sync/service.py",
            "function: retry_request",
            "urllib3",
            "HTTP 503 responses may be retried.",
            "delivery-boundary",
            "External delivery adapter",
        ):
            self.assertIn(expected, brief_text)
        self.assertNotIn("PUBLIC_SOURCE_BODY_CANARY", brief_text)
        self.assertNotIn("PUBLIC_COMMENT_CANARY", brief_text)
        self.assertIn("PUBLIC_SOURCE_BODY_CANARY", source_brief_text)
        self.assertIn("PUBLIC_COMMENT_CANARY", source_brief_text)
        self.assertIn("deliver_internal", source_brief_text)
        self.assertNotIn("PUBLIC_DOCSTRING_CANARY", source_brief_text)
        self.assertNotIn("PUBLIC_STRING_CANARY", source_brief_text)
        for result in (first, second):
            index_text = result.index.decode("utf-8")
            main_output = result.brief.decode("utf-8")
            all_output = result.terminal + main_output + result.source_brief.decode("utf-8")
            for canary in PUBLIC_CANARIES:
                self.assertNotIn(canary.casefold(), main_output.casefold())
            for private in STRICT_PRIVATE_VALUES:
                self.assertNotIn(private.casefold(), (index_text + all_output).casefold())
            self.assertNotIn(result.root, index_text + all_output)


if __name__ == "__main__":
    unittest.main()
