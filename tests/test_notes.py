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
from silobrief.state import SetupError
from tests.windows_junctions import directory_junction


@contextlib.contextmanager
def working_directory(path: Path) -> Iterator[None]:
    previous = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous)


def read_notes(project: Path) -> dict[str, object]:
    value: object = json.loads((project / ".silobrief" / "notes.json").read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise AssertionError("notes must be a JSON object")
    return {str(key): item for key, item in value.items()}


class HumanNotesTests(unittest.TestCase):
    def assert_log_error(self, arguments: list[str]) -> str:
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr), self.assertRaises(SystemExit) as caught:
            main(["log", *arguments])
        self.assertEqual(caught.exception.code, 2)
        return stderr.getvalue()

    def test_log_preserves_order_and_is_independent_of_absolute_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            projects = (root / "first", root / "second")
            rendered: list[bytes] = []

            for project in projects:
                package = project / "package"
                package.mkdir(parents=True)
                source = package / "service.py"
                source.write_text("VALUE = 1\n", encoding="utf-8", newline="\n")
                source_digest = hashlib.sha256(source.read_bytes()).digest()
                self.assertEqual(main(["setup", str(project)]), 0)
                index = project / ".silobrief" / "index.json"
                index.write_text(
                    '{"index_version": 1, "stale": false}\n',
                    encoding="utf-8",
                    newline="\n",
                )
                fixed_time = 1_700_000_000_000_000_000
                os.utime(index, ns=(fixed_time, fixed_time))
                index_before = (index.read_bytes(), index.stat().st_mtime_ns)
                stdout = io.StringIO()
                stderr = io.StringIO()

                with (
                    working_directory(project),
                    contextlib.redirect_stdout(stdout),
                    contextlib.redirect_stderr(stderr),
                ):
                    self.assertEqual(
                        main(
                            [
                                "log",
                                "package/service.py",
                                "--comment",
                                " Handles retry policy ",
                            ]
                        ),
                        0,
                    )
                with (
                    working_directory(package),
                    contextlib.redirect_stdout(stdout),
                    contextlib.redirect_stderr(stderr),
                ):
                    self.assertEqual(
                        main(["log", ".", "--comment", "Package maintenance context"]),
                        0,
                    )

                notes_path = project / ".silobrief" / "notes.json"
                rendered.append(notes_path.read_bytes())
                notes = read_notes(project)["notes"]
                if not isinstance(notes, list) or len(notes) != 2:
                    self.fail("two notes must be stored")
                first, second = notes
                if not isinstance(first, dict) or not isinstance(second, dict):
                    self.fail("notes must be objects")
                self.assertEqual(first.get("path"), "package/service.py")
                self.assertEqual(first.get("comment"), " Handles retry policy ")
                self.assertEqual(second.get("path"), "package")
                self.assertEqual(second.get("comment"), "Package maintenance context")
                first_id = first.get("id")
                second_id = second.get("id")
                self.assertIsInstance(first_id, str)
                self.assertIsInstance(second_id, str)
                self.assertRegex(str(first_id), r"note-[0-9a-f]{64}")
                self.assertRegex(str(second_id), r"note-[0-9a-f]{64}")
                self.assertNotEqual(first_id, second_id)
                self.assertEqual(index_before, (index.read_bytes(), index.stat().st_mtime_ns))
                self.assertEqual(hashlib.sha256(source.read_bytes()).digest(), source_digest)
                self.assertEqual(stderr.getvalue().count("may be included in the final brief"), 2)
                self.assertEqual(stdout.getvalue().count("updated .silobrief/notes.json"), 2)

            self.assertEqual(rendered[0], rendered[1])
            self.assertNotIn(str(projects[0]).encode(), rendered[0])
            self.assertNotIn(str(projects[1]).encode(), rendered[1])

    def test_log_rejects_invalid_or_excluded_paths_and_blank_comment(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project"
            project.mkdir()
            allowed = project / "allowed.py"
            allowed.write_text("pass\n", encoding="utf-8", newline="\n")
            private = project / "private.py"
            private.write_text("pass\n", encoding="utf-8", newline="\n")
            (project / ".git").mkdir()
            outside = root / "outside.py"
            outside.write_text("pass\n", encoding="utf-8", newline="\n")
            self.assertEqual(main(["setup", str(project)]), 0)
            with working_directory(project), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(["ignore", "private.py", "--as", "Private module"]), 0)
            notes = project / ".silobrief" / "notes.json"
            before = notes.read_bytes()
            cases = [
                [str(allowed.resolve()), "--comment", "Absolute"],
                ["../outside.py", "--comment", "Parent"],
                ["missing.py", "--comment", "Missing"],
                [".git", "--comment", "Default excluded"],
                ["private.py", "--comment", "Boundary"],
                ["allowed.py", "--comment", " \t"],
            ]

            with working_directory(project):
                for arguments in cases:
                    with self.subTest(arguments=arguments):
                        self.assert_log_error(arguments)
                        self.assertEqual(notes.read_bytes(), before)

    def test_log_rejects_symlink_target_and_component(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project"
            actual = project / "actual"
            actual.mkdir(parents=True)
            source = actual / "service.py"
            source.write_text("pass\n", encoding="utf-8", newline="\n")
            self.assertEqual(main(["setup", str(project)]), 0)
            file_link = project / "service-link.py"
            directory_link = project / "directory-link"
            try:
                file_link.symlink_to(source)
                directory_link.symlink_to(actual, target_is_directory=True)
            except OSError as error:
                self.skipTest(f"symbolic links unavailable: {error}")
            notes = project / ".silobrief" / "notes.json"
            before = notes.read_bytes()

            with working_directory(project):
                for path_text in ("service-link.py", "directory-link/service.py"):
                    with self.subTest(path=path_text):
                        self.assert_log_error([path_text, "--comment", "Must fail"])
                        self.assertEqual(notes.read_bytes(), before)

    @unittest.skipUnless(os.name == "nt", "directory junctions require Windows")
    def test_log_rejects_a_directory_junction_component(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "project"
            actual = project / "actual"
            actual.mkdir(parents=True)
            (actual / "service.py").write_text("pass\n", encoding="utf-8")
            self.assertEqual(main(["setup", str(project)]), 0)
            notes = project / ".silobrief" / "notes.json"
            before = notes.read_bytes()

            with directory_junction(project / "linked", actual), working_directory(project):
                self.assert_log_error(["linked/service.py", "--comment", "Must fail"])

            self.assertEqual(notes.read_bytes(), before)

    def test_state_rejects_invalid_note_entries(self) -> None:
        invalid_notes: list[object] = [
            "not-an-object",
            {"id": "note-short", "path": "module.py", "comment": "Context"},
            {"id": f"note-{'a' * 64}", "path": "../module.py", "comment": "Context"},
            {"id": f"note-{'a' * 64}", "path": "module.py", "comment": "   "},
            {
                "id": f"note-{'a' * 64}",
                "path": "module.py",
                "comment": "Context",
                "extra": True,
            },
        ]

        for invalid in invalid_notes:
            with self.subTest(invalid=invalid), tempfile.TemporaryDirectory() as directory:
                project = Path(directory)
                self.assertEqual(main(["setup", str(project)]), 0)
                notes = project / ".silobrief" / "notes.json"
                notes.write_text(
                    json.dumps({"notes": [invalid], "notes_version": 1}) + "\n",
                    encoding="utf-8",
                    newline="\n",
                )
                before = notes.read_bytes()

                with (
                    contextlib.redirect_stderr(io.StringIO()),
                    self.assertRaises(SystemExit) as caught,
                ):
                    main(["setup", str(project)])

                self.assertEqual(caught.exception.code, 2)
                self.assertEqual(notes.read_bytes(), before)

    def test_log_preserves_notes_when_atomic_save_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            source = project / "module.py"
            source.write_text("pass\n", encoding="utf-8", newline="\n")
            self.assertEqual(main(["setup", str(project)]), 0)
            notes = project / ".silobrief" / "notes.json"
            before = notes.read_bytes()
            stderr = io.StringIO()

            with (
                working_directory(project),
                contextlib.redirect_stderr(stderr),
                mock.patch("silobrief.notes.save_notes", side_effect=SetupError("write failed")),
            ):
                with self.assertRaises(SystemExit) as caught:
                    main(["log", "module.py", "--comment", "Public context"])

            self.assertEqual(caught.exception.code, 2)
            self.assertEqual(notes.read_bytes(), before)
            self.assertLess(
                stderr.getvalue().index("may be included in the final brief"),
                stderr.getvalue().index("write failed"),
            )


if __name__ == "__main__":
    unittest.main()
