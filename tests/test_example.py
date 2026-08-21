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
from tests.windows_junctions import directory_junction


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
                    "app.py",
                    "internal/__init__.py",
                    "internal/carrier_contract.py",
                    "pricing.py",
                    "requirements.txt",
                    "shipping.py",
                    "tests/__init__.py",
                    "tests/test_app.py",
                    "tests/test_pricing.py",
                    "tests/test_shipping.py",
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
                "python -m pip install -r requirements.txt",
                "sb setup .",
                "sb ignore internal",
                "sb init",
                "sb log",
                "sb search",
                "sb brief",
                "Guided maintenance task",
                "1000-unit remote-area surcharge",
                "carrier-boundary",
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

    def test_guided_task_reaches_a_boundary_safe_brief_through_the_public_workflow(self) -> None:
        prompt = (
            "Add a 1000-unit remote-area surcharge to calculate_shipping_price. Apply it after the "
            "weight surcharge. Preserve the Flask response shape and return a readable diff and "
            "focused unittests."
        )
        review_input = "y\n\npricing.py\n1\nr3\n\n\ny\ny\ny\ny\ny\ny\nn\nWRITE\n"
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "practice"
            self.assertEqual(main(["example", str(project)]), 0)

            with working_directory(project):
                self.assertEqual(main(["setup", "."]), 0)
                self.assertEqual(
                    main(
                        [
                            "ignore",
                            "internal",
                            "--as",
                            "Private carrier contract rules",
                            "--alias",
                            "carrier-boundary",
                        ]
                    ),
                    0,
                )
                self.assertEqual(main(["init"]), 0)
                self.assertEqual(
                    main(
                        [
                            "log",
                            "pricing.py",
                            "--comment",
                            "Weight is a positive whole number in kilograms.",
                        ]
                    ),
                    0,
                )
                index_text = Path(".silobrief/index.json").read_text(encoding="utf-8")
                self.assertIn("carrier-boundary", index_text)
                self.assertIn("Private carrier contract rules", index_text)
                self.assertNotIn("carrier_contract", index_text)
                self.assertNotIn("INTERNAL_CONTRACT_CANARY_7F4A", index_text)

                search_output = io.StringIO()
                with contextlib.redirect_stdout(search_output):
                    self.assertEqual(main(["search", prompt]), 0)
                self.assertIn("calculate_shipping_price", search_output.getvalue())

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
                            "brief",
                            prompt,
                            "--out",
                            ".silobrief/exports/remote-surcharge.md",
                        ]
                    )

            brief = project / ".silobrief/exports/remote-surcharge.md"
            self.assertEqual(result, 0, stdout.getvalue() + stderr.getvalue())
            self.assertEqual(stderr.getvalue(), "")
            self.assertTrue(brief.is_file())
            content = brief.read_text(encoding="utf-8")
            self.assertIn(prompt, content)
            self.assertIn("function: calculate_shipping_price", content)
            self.assertIn("function: quote_shipping", content)
            self.assertIn("def calculate_shipping_price(", content)
            self.assertIn("carrier-boundary", content)
            self.assertIn("Private carrier contract rules", content)
            self.assertNotIn("carrier_contract", content)
            self.assertNotIn("apply_contract_adjustment", content)
            self.assertNotIn("INTERNAL_CONTRACT_CANARY_7F4A", content)
            self.assertIn("source_delivery: embedded", content)
            self.assertFalse(brief.with_name("remote-surcharge.sources.md").exists())

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

    @unittest.skipUnless(os.name == "nt", "directory junctions require Windows")
    def test_rejects_a_directory_junction_target(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "target"
            target.mkdir()

            with directory_junction(root / "practice", target) as junction:
                message = self.assert_example_error(junction)

            self.assertIn("reparse point", message)
            self.assertEqual(list(target.iterdir()), [])

    def test_generation_does_not_change_the_working_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            before = Path.cwd()

            self.assertEqual(main(["example", str(Path(directory) / "practice")]), 0)

            self.assertEqual(Path.cwd(), before)


if __name__ == "__main__":
    unittest.main()
