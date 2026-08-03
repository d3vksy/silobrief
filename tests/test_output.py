from __future__ import annotations

import io
import tempfile
import unittest
from pathlib import Path
from typing import TextIO, cast

from silobrief.output import (
    OutputBlockedError,
    _uses_foreign_windows_path,
    approve_and_write,
)
from silobrief.renderer import BriefInput, RenderedBrief, render_brief
from silobrief.state import setup_project


class TtyBuffer(io.StringIO):
    def __init__(self, value: str = "", *, tty: bool = True) -> None:
        super().__init__(value)
        self.tty = tty
        self.flush_count = 0

    def isatty(self) -> bool:
        return self.tty

    def flush(self) -> None:
        self.flush_count += 1
        super().flush()


class RacingInput:
    def __init__(self, target: Path) -> None:
        self.target = target

    def isatty(self) -> bool:
        return True

    def readline(self, size: int = -1) -> str:
        self.target.write_text("rival content", encoding="utf-8")
        return "WRITE\n" if size != 0 else ""


def rendered_brief() -> RenderedBrief:
    return render_brief(
        BriefInput(
            user_prompt="공식 문서를 확인해줘",
            relative_paths=("src/api.py",),
            symbols=(),
            public_dependencies=("Python",),
            human_notes=(),
            boundaries=(),
        )
    )


def project_in(directory: str) -> Path:
    project = Path(directory) / "project"
    project.mkdir()
    setup_project(project)
    return project


class ApprovedOutputTests(unittest.TestCase):
    def test_distinguishes_posix_absolute_paths_from_windows_syntax(self) -> None:
        self.assertFalse(_uses_foreign_windows_path("/tmp/brief.md", platform="posix"))
        self.assertTrue(_uses_foreign_windows_path("C:\\temp\\brief.md", platform="posix"))
        self.assertTrue(_uses_foreign_windows_path("\\temp\\brief.md", platform="posix"))
        self.assertFalse(_uses_foreign_windows_path("C:\\temp\\brief.md", platform="nt"))

    def test_previews_full_markdown_and_writes_new_utf8_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = project_in(directory)
            rendered = rendered_brief()
            stdin = TtyBuffer("WRITE\n")
            stdout = TtyBuffer()

            result = approve_and_write(
                project,
                ".silobrief/exports/result.md",
                rendered,
                start=project,
                input_stream=stdin,
                output_stream=stdout,
            )

            destination = project / ".silobrief" / "exports" / "result.md"
            self.assertEqual(result, destination.resolve())
            self.assertEqual(destination.read_bytes(), rendered.markdown.encode("utf-8"))
            self.assertTrue(stdout.getvalue().startswith(rendered.markdown))
            self.assertIn("exactly WRITE", stdout.getvalue())
            self.assertGreaterEqual(stdout.flush_count, 1)
            self.assertEqual([path.name for path in destination.parent.iterdir()], ["result.md"])

    def test_allows_explicit_output_outside_the_project(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = project_in(directory)
            outside = Path(directory) / "outside"
            outside.mkdir()
            destination = outside / "brief.md"

            result = approve_and_write(
                project,
                str(destination),
                rendered_brief(),
                start=project,
                input_stream=TtyBuffer("WRITE\r\n"),
                output_stream=TtyBuffer(),
            )

            self.assertEqual(result, destination.resolve())
            self.assertTrue(destination.is_file())

    def test_requires_both_ttys_and_an_exact_approval(self) -> None:
        cases = (
            (False, True, "WRITE\n"),
            (True, False, "WRITE\n"),
            (True, True, "write\n"),
            (True, True, " WRITE\n"),
            (True, True, "WRITE \n"),
            (True, True, "YES\n"),
            (True, True, ""),
        )
        with tempfile.TemporaryDirectory() as directory:
            project = project_in(directory)
            exports = project / ".silobrief" / "exports"
            before = tuple(exports.iterdir())

            for number, (input_tty, output_tty, approval) in enumerate(cases):
                with self.subTest(approval=approval, input_tty=input_tty, output_tty=output_tty):
                    destination = f".silobrief/exports/refused-{number}.md"
                    with self.assertRaises(OutputBlockedError):
                        approve_and_write(
                            project,
                            destination,
                            rendered_brief(),
                            start=project,
                            input_stream=TtyBuffer(approval, tty=input_tty),
                            output_stream=TtyBuffer(tty=output_tty),
                        )
                    self.assertFalse((project / destination).exists())
                    self.assertEqual(tuple(exports.iterdir()), before)

    def test_rejects_invalid_and_existing_output_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = project_in(directory)
            outside = Path(directory) / "outside"
            outside.mkdir()
            existing = project / ".silobrief" / "exports" / "existing.md"
            existing.write_text("keep this", encoding="utf-8")
            existing_directory = project / ".silobrief" / "exports" / "folder.md"
            existing_directory.mkdir()
            cases = (
                "result.md",
                ".silobrief/exports/result.txt",
                ".silobrief/exports/result.MD",
                ".silobrief/exports/missing/result.md",
                "../outside/traversal.md",
                ".silobrief/exports\\mixed.md",
                ".silobrief/exports/existing.md",
                ".silobrief/exports/folder.md",
            )

            for output in cases:
                with self.subTest(output=output):
                    with self.assertRaises(OutputBlockedError):
                        approve_and_write(
                            project,
                            output,
                            rendered_brief(),
                            start=project,
                            input_stream=TtyBuffer("WRITE\n"),
                            output_stream=TtyBuffer(),
                        )
            self.assertEqual(existing.read_text(encoding="utf-8"), "keep this")
            self.assertTrue(existing_directory.is_dir())
            self.assertFalse((outside / "traversal.md").exists())

    def test_exclusive_creation_blocks_a_file_created_during_approval(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = project_in(directory)
            destination = project / ".silobrief" / "exports" / "race.md"

            with self.assertRaisesRegex(OutputBlockedError, "already exists"):
                approve_and_write(
                    project,
                    ".silobrief/exports/race.md",
                    rendered_brief(),
                    start=project,
                    input_stream=cast(TextIO, RacingInput(destination)),
                    output_stream=TtyBuffer(),
                )

            self.assertEqual(destination.read_text(encoding="utf-8"), "rival content")

    def test_rejects_output_and_parent_symbolic_links(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = project_in(directory)
            exports = project / ".silobrief" / "exports"
            outside = Path(directory) / "outside"
            outside.mkdir()
            target = outside / "target.md"
            target.write_text("target content", encoding="utf-8")
            output_link = exports / "linked.md"
            parent_link = exports / "linked-parent"
            try:
                output_link.symlink_to(target)
                parent_link.symlink_to(outside, target_is_directory=True)
            except OSError as error:
                self.skipTest(f"symbolic links are unavailable: {error}")

            for output in (
                ".silobrief/exports/linked.md",
                ".silobrief/exports/linked-parent/result.md",
            ):
                with self.subTest(output=output):
                    with self.assertRaisesRegex(OutputBlockedError, "symbolic link"):
                        approve_and_write(
                            project,
                            output,
                            rendered_brief(),
                            start=project,
                            input_stream=TtyBuffer("WRITE\n"),
                            output_stream=TtyBuffer(),
                        )
            self.assertEqual(target.read_text(encoding="utf-8"), "target content")
            self.assertFalse((outside / "result.md").exists())


if __name__ == "__main__":
    unittest.main()
