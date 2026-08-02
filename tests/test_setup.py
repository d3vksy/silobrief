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
    def test_setup_creates_initial_state_without_changing_source(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            source = project / "service.py"
            source.write_text("VALUE = 1\n", encoding="utf-8", newline="\n")
            source_digest = hashlib.sha256(source.read_bytes()).digest()

            result = main(["setup", str(project)])

            state = project / ".silobrief"
            self.assertEqual(result, 0)
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
            self.assertNotIn(b"\r\n", (state / "config.json").read_bytes())
            self.assertTrue((state / "config.json").read_bytes().endswith(b"\n"))

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

            result = main(["setup", str(project)])

            after = [
                (path.read_bytes() if path.is_file() else b"", path.stat().st_mtime_ns)
                for path in tracked
            ]
            self.assertEqual(result, 0)
            self.assertEqual(after, before)

    def test_setup_rejects_missing_path_and_regular_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            regular_file = root / "project.py"
            regular_file.write_text("pass\n", encoding="utf-8", newline="\n")

            for invalid_path in (root / "missing", regular_file):
                with self.subTest(path=invalid_path), contextlib.redirect_stderr(io.StringIO()):
                    with self.assertRaises(SystemExit) as caught:
                        main(["setup", str(invalid_path)])

                self.assertEqual(caught.exception.code, 2)
