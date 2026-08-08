from __future__ import annotations

import contextlib
import io
import os
import sys
import tempfile
import unittest
from collections.abc import Iterator
from pathlib import Path
from unittest import mock

from silobrief.cli import main


class TtyBuffer(io.StringIO):
    def __init__(self, value: str = "", *, tty: bool = True) -> None:
        super().__init__(value)
        self.tty = tty

    def isatty(self) -> bool:
        return self.tty


class ScriptedInput:
    def __init__(self, value: str, target: Path, *, tty: bool = True) -> None:
        self._stream = io.StringIO(value)
        self.target = target
        self.source_target = target.with_name(f"{target.stem}.sources.md")
        self.tty = tty
        self.output_absent_before_write: bool | None = None
        self.source_output_absent_before_write: bool | None = None

    def isatty(self) -> bool:
        return self.tty

    def readline(self, size: int = -1) -> str:
        value = self._stream.readline(size)
        if value.rstrip("\r\n") == "WRITE":
            self.output_absent_before_write = not self.target.exists()
            self.source_output_absent_before_write = not self.source_target.exists()
        return value


@contextlib.contextmanager
def working_directory(path: Path) -> Iterator[None]:
    previous = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous)


def source_bytes(project: Path) -> dict[str, bytes]:
    return {
        path.relative_to(project).as_posix(): path.read_bytes()
        for path in sorted(project.rglob("*.py"))
    }


def prepare_project(project: Path) -> Path:
    package = project / "package"
    private = project / "private"
    package.mkdir()
    private.mkdir()
    service = package / "service.py"
    service.write_text(
        "import urllib3\n"
        "from private.secret import send\n\n"
        "SOURCE_CANARY = 'allowed-source-canary'\n\n"
        "def run():\n"
        "    send()\n"
        "    return urllib3\n",
        encoding="utf-8",
        newline="\n",
    )
    (private / "secret.py").write_text(
        "PRIVATE_CANARY = 'private-boundary-canary'\n\ndef send():\n    return None\n",
        encoding="utf-8",
        newline="\n",
    )

    if main(["setup", str(project)]) != 0:
        raise AssertionError("setup failed")
    with (
        working_directory(project),
        contextlib.redirect_stdout(io.StringIO()),
        contextlib.redirect_stderr(io.StringIO()),
    ):
        results = (
            main(
                [
                    "ignore",
                    "private",
                    "--as",
                    "External delivery adapter",
                    "--alias",
                    "delivery-boundary",
                ]
            ),
            main(["init"]),
            main(["log", "package/service.py", "--comment", "Python 3.10 is required"]),
        )
    if results != (0, 0, 0):
        raise AssertionError(f"project preparation failed: {results}")
    return service


REVIEW_INPUT = "y\n1\n\n\ny\ny\ny\ny\ny\ny\nEXPOSE\n"
NO_SOURCE_REVIEW_INPUT = "y\n1\n\n\ny\ny\ny\ny\ny\nn\n"
GUIDED_REVIEW_INPUT = "y\n\npackage/service.py\n1\n\n\ny\ny\ny\ny\ny\ny\nEXPOSE\n"


def run_chat(
    project: Path,
    output: str,
    input_text: str,
    *,
    tty: bool = True,
) -> tuple[int, ScriptedInput, str, str]:
    input_stream = ScriptedInput(input_text, project / output, tty=tty)
    stdout = TtyBuffer()
    stderr = io.StringIO()
    with (
        working_directory(project),
        mock.patch.object(sys, "stdin", input_stream),
        contextlib.redirect_stdout(stdout),
        contextlib.redirect_stderr(stderr),
    ):
        result = main(["chat", "run official docs", "--out", output])
    return result, input_stream, stdout.getvalue(), stderr.getvalue()


class ChatCommandTests(unittest.TestCase):
    def test_runs_the_full_cli_flow_and_writes_only_after_approval(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            prepare_project(project)
            before = source_bytes(project)
            output = ".silobrief/exports/run.md"

            result, input_stream, stdout, stderr = run_chat(
                project, output, REVIEW_INPUT + "WRITE\n"
            )

            destination = project / output
            source_destination = destination.with_name(f"{destination.stem}.sources.md")
            self.assertEqual(result, 0)
            self.assertIs(input_stream.output_absent_before_write, True)
            self.assertIs(input_stream.source_output_absent_before_write, True)
            self.assertTrue(destination.is_file())
            self.assertTrue(source_destination.is_file())
            self.assertEqual(source_bytes(project), before)
            self.assertEqual(stderr, "")
            self.assertIn("Candidates:", stdout)
            self.assertIn("wrote .silobrief/exports/run.md", stdout)
            markdown = destination.read_text(encoding="utf-8")
            source_markdown = source_destination.read_text(encoding="utf-8")
            for approved in (
                "package/service.py",
                "function: run",
                "urllib3",
                "Python 3.10 is required",
                "delivery-boundary",
                "External delivery adapter",
            ):
                self.assertIn(approved, markdown)
            self.assertIn("def run():", source_markdown)
            self.assertIn("send()", source_markdown)
            for hidden in (
                "allowed-source-canary",
                "private-boundary-canary",
                "private.secret",
                str(project),
            ):
                self.assertNotIn(hidden, stdout + markdown + source_markdown)

    def test_writes_only_the_main_brief_when_source_is_declined(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            prepare_project(project)
            output = ".silobrief/exports/context-only.md"

            result, _, _, stderr = run_chat(
                project,
                output,
                NO_SOURCE_REVIEW_INPUT + "WRITE\n",
            )

            destination = project / output
            self.assertEqual(result, 0)
            self.assertEqual(stderr, "")
            self.assertTrue(destination.is_file())
            self.assertFalse(destination.with_name("context-only.sources.md").exists())
            self.assertIn('source_companion: "none"', destination.read_text(encoding="utf-8"))

    def test_src_layout_boundary_is_redacted_in_exact_path_brief(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            package = project / "src" / "pkg"
            package.mkdir(parents=True)
            (package / "app.py").write_text(
                "from pkg.secretmod import hidden_internal_name\n\n"
                "def run():\n"
                "    return hidden_internal_name()\n",
                encoding="utf-8",
                newline="\n",
            )
            (package / "secretmod.py").write_text(
                "def hidden_internal_name():\n    return 'PRIVATE_CANARY'\n",
                encoding="utf-8",
                newline="\n",
            )

            self.assertEqual(main(["setup", str(project)]), 0)
            with working_directory(project):
                self.assertEqual(
                    main(
                        [
                            "ignore",
                            "src/pkg/secretmod.py",
                            "--as",
                            "Approved internal module",
                            "--alias",
                            "secret-boundary",
                        ]
                    ),
                    0,
                )
                self.assertEqual(main(["init"]), 0)

            output = ".silobrief/exports/src-layout.md"
            review = "y\n\nsrc/pkg/app.py\n1\n\n\ny\ny\ny\nn\ny\nn\nWRITE\n"
            result, _, _, stderr = run_chat(project, output, review)

            destination = project / output
            self.assertEqual(result, 0)
            self.assertEqual(stderr, "")
            generated = destination.read_text(encoding="utf-8")
            self.assertIn("secret-boundary", generated)
            self.assertIn("Approved internal module", generated)
            for forbidden in ("pkg.secretmod", "hidden_internal_name", "PRIVATE_CANARY"):
                with self.subTest(forbidden=forbidden):
                    self.assertNotIn(forbidden, generated)

    def test_selects_an_approved_source_from_a_file_outline(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            prepare_project(project)
            output = ".silobrief/exports/guided.md"

            result, _, stdout, stderr = run_chat(
                project,
                output,
                GUIDED_REVIEW_INPUT + "WRITE\n",
            )

            destination = project / output
            source_destination = destination.with_name("guided.sources.md")
            self.assertEqual(result, 0)
            self.assertEqual(stderr, "")
            self.assertIn("Symbols in `package/service.py`:", stdout)
            self.assertIn("1. function run", stdout)
            generated = source_destination.read_text(encoding="utf-8")
            self.assertIn("def run():", generated)
            self.assertNotIn("private-boundary-canary", generated)

    def test_rejects_an_invalid_guided_symbol_without_writing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            prepare_project(project)
            output = ".silobrief/exports/invalid-guided.md"

            result, _, _, stderr = run_chat(
                project,
                output,
                "y\n\npackage/service.py\n2\n",
            )

            self.assertEqual(result, 4)
            self.assertIn("unknown symbol number", stderr)
            self.assertFalse((project / output).exists())
            self.assertFalse((project / ".silobrief/exports/invalid-guided.sources.md").exists())

    def test_explains_python_only_scope_when_index_has_no_sources(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            source = project / "src" / "App.tsx"
            source.parent.mkdir()
            source.write_text(
                "export function App() { return <button>Start</button>; }\n",
                encoding="utf-8",
                newline="\n",
            )
            before = source.read_bytes()
            self.assertEqual(main(["setup", str(project)]), 0)
            init_stderr = io.StringIO()
            with (
                working_directory(project),
                contextlib.redirect_stdout(io.StringIO()),
                contextlib.redirect_stderr(init_stderr),
            ):
                self.assertEqual(main(["init"]), 0)

            output = ".silobrief/exports/frontend.md"
            result, _, _, chat_stderr = run_chat(project, output, "y\n\n\n")

            self.assertIn("no supported Python files were found", init_stderr.getvalue())
            self.assertEqual(result, 4)
            self.assertIn("siloBrief currently supports Python projects only", chat_stderr)
            self.assertFalse((project / output).exists())
            self.assertFalse((project / ".silobrief/exports/frontend.sources.md").exists())
            self.assertEqual(source.read_bytes(), before)

    def test_maps_invalid_input_and_index_state_to_contract_codes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            self.assertEqual(main(["setup", str(project)]), 0)
            stderr = io.StringIO()
            with (
                working_directory(project),
                contextlib.redirect_stderr(stderr),
                self.assertRaises(SystemExit) as caught,
            ):
                main(["chat", " ", "--out", ".silobrief/exports/blank.md"])
            self.assertEqual(caught.exception.code, 2)
            self.assertIn("request", stderr.getvalue())

            stderr = io.StringIO()
            with (
                contextlib.redirect_stderr(stderr),
                self.assertRaises(SystemExit) as caught,
            ):
                main(["chat", "request", "--out", " "])
            self.assertEqual(caught.exception.code, 2)
            self.assertIn("output path", stderr.getvalue())

            result, _, _, stderr_text = run_chat(project, ".silobrief/exports/missing.md", "")
            self.assertEqual(result, 3)
            self.assertIn("run sb init", stderr_text)

            index = project / ".silobrief/index.json"
            index.write_text("{", encoding="utf-8")
            result, _, _, stderr_text = run_chat(project, ".silobrief/exports/corrupt.md", "")
            self.assertEqual(result, 3)
            self.assertIn("cannot read index.json", stderr_text)

            index.write_text('{"index_version": 2}\n', encoding="utf-8", newline="\n")
            result, _, _, stderr_text = run_chat(project, ".silobrief/exports/incompatible.md", "")
            self.assertEqual(result, 3)
            self.assertIn("not compatible", stderr_text)

        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            service = prepare_project(project)
            service.write_text("def changed():\n    return 1\n", encoding="utf-8")
            result, _, _, stderr_text = run_chat(project, ".silobrief/exports/changed.md", "")
            self.assertEqual(result, 4)
            self.assertIn("sources changed", stderr_text)
            self.assertFalse((project / ".silobrief/exports/changed.md").exists())

    def test_blocks_non_tty_refusal_and_existing_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            prepare_project(project)

            result, _, _, stderr = run_chat(
                project,
                ".silobrief/exports/non-tty.md",
                REVIEW_INPUT + "WRITE\n",
                tty=False,
            )
            self.assertEqual(result, 4)
            self.assertIn("interactive terminal", stderr)

            refused = ".silobrief/exports/refused.md"
            result, _, _, stderr = run_chat(project, refused, REVIEW_INPUT + "NO\n")
            self.assertEqual(result, 4)
            self.assertIn("exact WRITE", stderr)
            self.assertFalse((project / refused).exists())
            self.assertFalse((project / ".silobrief/exports/refused.sources.md").exists())

            existing = project / ".silobrief/exports/existing.md"
            existing.write_text("keep", encoding="utf-8")
            result, _, _, stderr = run_chat(
                project, ".silobrief/exports/existing.md", REVIEW_INPUT + "WRITE\n"
            )
            self.assertEqual(result, 4)
            self.assertIn("already exists", stderr)
            self.assertEqual(existing.read_text(encoding="utf-8"), "keep")
