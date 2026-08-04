from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import tempfile
import unittest
from collections.abc import Iterator
from pathlib import Path
from unittest import mock

from silobrief.cli import main

DEFAULT_EXCLUDES = [
    ".git/",
    ".silobrief/",
    "__pycache__/",
    ".venv/",
    "venv/",
    "build/",
    "dist/",
]


@contextlib.contextmanager
def working_directory(path: Path) -> Iterator[None]:
    previous = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous)


class SetupCommandTests(unittest.TestCase):
    def assert_setup_error(self, project: Path) -> str:
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr), self.assertRaises(SystemExit) as caught:
            main(["setup", str(project)])
        self.assertEqual(caught.exception.code, 2)
        return stderr.getvalue()

    def test_setup_creates_initial_state_without_changing_source(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            source = project / "service.py"
            source.write_text("VALUE = 1\n", encoding="utf-8", newline="\n")
            source_digest = hashlib.sha256(source.read_bytes()).digest()

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                result = main(["setup", str(project)])

            state = project / ".silobrief"
            self.assertEqual(result, 0)
            self.assertEqual(
                stdout.getvalue(),
                "created .silobrief/config.json, .silobrief/notes.json, and .silobrief/exports/\n",
            )
            self.assertEqual(
                json.loads((state / "config.json").read_text(encoding="utf-8")),
                {
                    "boundaries": [],
                    "default_excludes": DEFAULT_EXCLUDES,
                    "schema_version": 1,
                },
            )
            self.assertEqual(
                json.loads((state / "notes.json").read_text(encoding="utf-8")),
                {"notes": [], "notes_version": 1},
            )
            self.assertTrue((state / "exports").is_dir())
            self.assertFalse((state / "index.json").exists())
            self.assertEqual(hashlib.sha256(source.read_bytes()).digest(), source_digest)
            expected_config = (
                json.dumps(
                    {
                        "boundaries": [],
                        "default_excludes": DEFAULT_EXCLUDES,
                        "schema_version": 1,
                    },
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
                + "\n"
            ).encode()
            self.assertEqual((state / "config.json").read_bytes(), expected_config)

    def test_setup_defaults_to_current_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)

            with working_directory(project):
                result = main(["setup"])

            self.assertEqual(result, 0)
            self.assertTrue((project / ".silobrief" / "config.json").is_file())

    def test_setup_keeps_valid_state_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            self.assertEqual(main(["setup", str(project)]), 0)
            state = project / ".silobrief"
            tracked = [state / "config.json", state / "notes.json", state / "exports"]
            fixed_time = 1_700_000_000_000_000_000
            for path in tracked:
                os.utime(path, ns=(fixed_time, fixed_time))
            before = [
                (path.read_bytes() if path.is_file() else b"", path.stat().st_mtime_ns)
                for path in tracked
            ]

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                result = main(["setup", str(project)])

            after = [
                (path.read_bytes() if path.is_file() else b"", path.stat().st_mtime_ns)
                for path in tracked
            ]
            self.assertEqual(result, 0)
            self.assertEqual(stdout.getvalue(), "validated existing .silobrief state\n")
            self.assertEqual(after, before)

    def test_setup_rejects_missing_path_and_regular_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            regular_file = root / "project.py"
            regular_file.write_text("pass\n", encoding="utf-8", newline="\n")

            for invalid_path in (root / "missing", regular_file):
                with self.subTest(path=invalid_path):
                    self.assert_setup_error(invalid_path)

    def test_setup_rejects_symbolic_link_project_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project"
            project.mkdir()
            link = root / "project-link"
            try:
                link.symlink_to(project, target_is_directory=True)
            except OSError as error:
                self.skipTest(f"symbolic links unavailable: {error}")

            message = self.assert_setup_error(link)

            self.assertIn("symbolic link", message)
            self.assertFalse((project / ".silobrief").exists())

            state_link_project = root / "state-link-project"
            state_link_project.mkdir()
            state_link = state_link_project / ".silobrief"
            state_link.symlink_to(project, target_is_directory=True)

            message = self.assert_setup_error(state_link_project)

            self.assertIn("real directory", message)
            self.assertEqual(list(project.iterdir()), [])

    def test_setup_rejects_state_file_and_partial_state_without_changes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state_file_project = root / "state-file"
            state_file_project.mkdir()
            state_file = state_file_project / ".silobrief"
            state_file.write_bytes(b"do not replace\n")

            self.assert_setup_error(state_file_project)
            self.assertEqual(state_file.read_bytes(), b"do not replace\n")

            partial_project = root / "partial"
            partial_project.mkdir()
            self.assertEqual(main(["setup", str(partial_project)]), 0)
            partial_state = partial_project / ".silobrief"
            partial_config = partial_state / "config.json"
            config_before = partial_config.read_bytes()
            (partial_state / "notes.json").unlink()

            self.assert_setup_error(partial_project)
            self.assertEqual(partial_config.read_bytes(), config_before)
            self.assertFalse((partial_state / "notes.json").exists())

    def test_setup_rejects_corrupt_and_incompatible_config_without_changes(self) -> None:
        valid_with_boolean_version = json.dumps(
            {
                "boundaries": [],
                "default_excludes": DEFAULT_EXCLUDES,
                "schema_version": True,
            },
            sort_keys=True,
        ).encode()
        cases = {
            "corrupt": b"{\n",
            "not-an-object": b"[]\n",
            "boolean-version": valid_with_boolean_version,
        }

        for name, replacement in cases.items():
            with self.subTest(case=name), tempfile.TemporaryDirectory() as directory:
                project = Path(directory)
                self.assertEqual(main(["setup", str(project)]), 0)
                config = project / ".silobrief" / "config.json"
                config.write_bytes(replacement)

                self.assert_setup_error(project)

                self.assertEqual(config.read_bytes(), replacement)

    def test_setup_rejects_incompatible_notes_and_index_versions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            self.assertEqual(main(["setup", str(project)]), 0)
            state = project / ".silobrief"
            notes = state / "notes.json"
            notes.write_text('{"notes": [], "notes_version": true}\n', encoding="utf-8")

            self.assert_setup_error(project)

            notes.write_text('{"notes": [], "notes_version": 1}\n', encoding="utf-8")
            index = state / "index.json"
            index.write_text('{"index_version": 2}\n', encoding="utf-8")

            self.assert_setup_error(project)
            self.assertEqual(index.read_text(encoding="utf-8"), '{"index_version": 2}\n')

    def test_setup_removes_new_state_after_write_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)

            with mock.patch("silobrief.state.Path.write_text", side_effect=OSError("disk full")):
                message = self.assert_setup_error(project)

            self.assertIn("cannot initialize", message)
            self.assertFalse((project / ".silobrief").exists())
