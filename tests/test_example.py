from __future__ import annotations

import contextlib
import hashlib
import io
import os
import subprocess
import sys
import tempfile
import unittest
from collections.abc import Iterator
from pathlib import Path
from unittest import mock

from silobrief.cli import main


class TtyBuffer(io.StringIO):
    def isatty(self) -> bool:
        return True


@contextlib.contextmanager
def working_directory(path: Path) -> Iterator[None]:
    previous = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous)


def file_manifest(root: Path) -> tuple[tuple[str, str], ...]:
    return tuple(
        (path.relative_to(root).as_posix(), hashlib.sha256(path.read_bytes()).hexdigest())
        for path in sorted(root.rglob("*"))
        if path.is_file()
    )


class ExampleCommandTests(unittest.TestCase):
    def assert_example_error(self, target: Path) -> str:
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr), self.assertRaises(SystemExit) as caught:
            main(["example", str(target)])
        self.assertEqual(caught.exception.code, 2)
        return stderr.getvalue()

    def test_creates_a_runnable_guided_project_without_initializing_silobrief(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "practice"
            stdout = io.StringIO()

            with contextlib.redirect_stdout(stdout):
                result = main(["example", str(project)])

            self.assertEqual(result, 0)
            self.assertIn("created example project", stdout.getvalue())
            self.assertFalse((project / ".silobrief").exists())
            self.assertEqual(
                {path for path, _digest in file_manifest(project)},
                {
                    "README.md",
                    "parcel_practice/__init__.py",
                    "parcel_practice/labels.py",
                    "parcel_practice/pricing.py",
                    "parcel_practice/references.py",
                    "tests/__init__.py",
                    "tests/test_labels.py",
                    "tests/test_pricing.py",
                    "tests/test_references.py",
                },
            )

            completed = subprocess.run(
                [sys.executable, "-m", "unittest", "discover", "-s", "tests"],
                cwd=project,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

            readme = (project / "README.md").read_text(encoding="utf-8")
            for expected in (
                "sb setup .",
                "sb init",
                "sb log",
                "sb chat",
                "Task 1: Modify",
                "Task 2: Add",
                "Task 3: Remove",
                "python -m unittest discover -s tests",
            ):
                self.assertIn(expected, readme)

    def test_generation_is_byte_identical_and_uses_lf(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / "first"
            second = root / "second"

            with (
                mock.patch("socket.create_connection") as create_connection,
                mock.patch("socket.socket.connect") as connect,
            ):
                self.assertEqual(main(["example", str(first)]), 0)
            create_connection.assert_not_called()
            connect.assert_not_called()
            self.assertEqual(main(["example", str(second)]), 0)

            self.assertEqual(file_manifest(first), file_manifest(second))
            for path in first.rglob("*"):
                if path.is_file():
                    self.assertNotIn(b"\r\n", path.read_bytes())

    def test_accepts_an_existing_empty_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "practice"
            project.mkdir()

            result = main(["example", str(project)])

            self.assertEqual(result, 0)
            self.assertTrue((project / "README.md").is_file())

    def test_first_task_reaches_a_single_brief_through_the_public_workflow(self) -> None:
        prompt = (
            "Append an optional separator to format_label. Preserve positional callers and apply "
            "uppercase last. Return a readable diff and focused unittests."
        )
        review_input = "y\n\nparcel_practice/labels.py\n1\n\n\ny\ny\ny\ny\ny\ny\nWRITE\n"
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "practice"
            self.assertEqual(main(["example", str(project)]), 0)

            with working_directory(project):
                self.assertEqual(main(["setup", "."]), 0)
                self.assertEqual(main(["init"]), 0)
                self.assertEqual(
                    main(
                        [
                            "log",
                            "parcel_practice/labels.py",
                            "--comment",
                            "Callers pass uppercase positionally.",
                        ]
                    ),
                    0,
                )
                stdin = TtyBuffer(review_input)
                stdout = TtyBuffer()
                stderr = io.StringIO()
                with (
                    mock.patch.object(sys, "stdin", stdin),
                    contextlib.redirect_stdout(stdout),
                    contextlib.redirect_stderr(stderr),
                ):
                    result = main(
                        [
                            "chat",
                            prompt,
                            "--out",
                            ".silobrief/exports/task-01-modify.md",
                        ]
                    )

            brief = project / ".silobrief/exports/task-01-modify.md"
            self.assertEqual(result, 0)
            self.assertEqual(stderr.getvalue(), "")
            self.assertTrue(brief.is_file())
            content = brief.read_text(encoding="utf-8")
            self.assertIn(prompt, content)
            self.assertIn("function: format_label", content)
            self.assertIn("def format_label(", content)
            self.assertIn("source_delivery: embedded", content)
            self.assertFalse(brief.with_name("task-01-modify.sources.md").exists())

    def test_rejects_a_file_and_nonempty_directory_without_changes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            regular_file = root / "practice.py"
            regular_file.write_bytes(b"keep me\n")
            nonempty = root / "existing"
            nonempty.mkdir()
            marker = nonempty / "marker.txt"
            marker.write_bytes(b"keep me too\n")

            file_message = self.assert_example_error(regular_file)
            directory_message = self.assert_example_error(nonempty)

            self.assertIn("directory", file_message)
            self.assertIn("empty", directory_message)
            self.assertEqual(regular_file.read_bytes(), b"keep me\n")
            self.assertEqual(marker.read_bytes(), b"keep me too\n")
            self.assertEqual(list(nonempty.iterdir()), [marker])

    def test_rejects_a_symbolic_link_target(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "target"
            target.mkdir()
            link = root / "practice"
            try:
                link.symlink_to(target, target_is_directory=True)
            except OSError as error:
                self.skipTest(f"symbolic links unavailable: {error}")

            message = self.assert_example_error(link)

            self.assertIn("symbolic link", message)
            self.assertEqual(list(target.iterdir()), [])

    def test_generation_does_not_change_the_working_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            before = Path.cwd()

            self.assertEqual(main(["example", str(Path(directory) / "practice")]), 0)

            self.assertEqual(Path.cwd(), before)


if __name__ == "__main__":
    unittest.main()
