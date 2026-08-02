from __future__ import annotations

import contextlib
import io
import json
import os
import tempfile
import unittest
from collections.abc import Iterator
from pathlib import Path

from silobrief.cli import main


@contextlib.contextmanager
def working_directory(path: Path) -> Iterator[None]:
    previous = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous)


def read_config(project: Path) -> dict[str, object]:
    value: object = json.loads((project / ".silobrief" / "config.json").read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise AssertionError("config must be a JSON object")
    return {str(key): item for key, item in value.items()}


class IgnoreCommandTests(unittest.TestCase):
    def assert_ignore_error(self, arguments: list[str]) -> str:
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr), self.assertRaises(SystemExit) as caught:
            main(["ignore", *arguments])
        self.assertEqual(caught.exception.code, 2)
        return stderr.getvalue()

    def test_ignore_registers_explicit_alias_from_project_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            private_file = project / "private_adapter.py"
            private_file.write_text("TOKEN = 'fixture'\n", encoding="utf-8", newline="\n")
            self.assertEqual(main(["setup", str(project)]), 0)
            stdout = io.StringIO()

            with working_directory(project), contextlib.redirect_stdout(stdout):
                result = main(
                    [
                        "ignore",
                        "private_adapter.py",
                        "--as",
                        "Private service adapter",
                        "--alias",
                        "internal-adapter",
                    ]
                )

            self.assertEqual(result, 0)
            self.assertEqual(
                read_config(project)["boundaries"],
                [
                    {
                        "alias": "internal-adapter",
                        "description": "Private service adapter",
                        "path": "private_adapter.py",
                    }
                ],
            )
            self.assertIn("internal-adapter", stdout.getvalue())
            self.assertIn("private_adapter.py", stdout.getvalue())

    def test_ignore_finds_root_from_subdirectory_and_assigns_aliases(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            package = project / "package"
            data = package / "private_data"
            data.mkdir(parents=True)
            private_file = package / "secret.py"
            private_file.write_text("VALUE = 1\n", encoding="utf-8", newline="\n")
            self.assertEqual(main(["setup", str(project)]), 0)

            with working_directory(package), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(["ignore", "secret.py", "--as", "Internal module"]), 0)
                self.assertEqual(main(["ignore", "private_data", "--as", "Internal data"]), 0)

            self.assertEqual(
                read_config(project)["boundaries"],
                [
                    {
                        "alias": "boundary-1",
                        "description": "Internal module",
                        "path": "package/secret.py",
                    },
                    {
                        "alias": "boundary-2",
                        "description": "Internal data",
                        "path": "package/private_data",
                    },
                ],
            )

    def test_ignore_re_registration_is_idempotent_and_conflict_safe(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            private_file = project / "private.py"
            private_file.write_text("pass\n", encoding="utf-8", newline="\n")
            self.assertEqual(main(["setup", str(project)]), 0)

            with working_directory(project), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(["ignore", "private.py", "--as", "Private module"]), 0)
            config = project / ".silobrief" / "config.json"
            fixed_time = 1_700_000_000_000_000_000
            os.utime(config, ns=(fixed_time, fixed_time))
            before = (config.read_bytes(), config.stat().st_mtime_ns)

            with working_directory(project), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(["ignore", "private.py", "--as", "Private module"]), 0)
            self.assertEqual((config.read_bytes(), config.stat().st_mtime_ns), before)

            with working_directory(project):
                self.assert_ignore_error(["private.py", "--as", "Different description"])
            self.assertEqual((config.read_bytes(), config.stat().st_mtime_ns), before)

    def test_ignore_marks_existing_index_stale_only_for_new_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            private_file = project / "private.py"
            private_file.write_text("pass\n", encoding="utf-8", newline="\n")
            self.assertEqual(main(["setup", str(project)]), 0)
            index = project / ".silobrief" / "index.json"
            index.write_text(
                '{"index_version": 1, "nodes": [], "stale": false}\n',
                encoding="utf-8",
                newline="\n",
            )

            with working_directory(project), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(["ignore", "private.py", "--as", "Private module"]), 0)

            index_data = json.loads(index.read_text(encoding="utf-8"))
            self.assertEqual(
                index_data,
                {"index_version": 1, "nodes": [], "stale": True},
            )
            fixed_time = 1_700_000_000_000_000_000
            os.utime(index, ns=(fixed_time, fixed_time))
            before = (index.read_bytes(), index.stat().st_mtime_ns)

            with working_directory(project), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(["ignore", "private.py", "--as", "Private module"]), 0)
            self.assertEqual((index.read_bytes(), index.stat().st_mtime_ns), before)
