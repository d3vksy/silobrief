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
from silobrief.state import SetupError, load_language_settings


@contextlib.contextmanager
def working_directory(path: Path) -> Iterator[None]:
    previous = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous)


def run_silently(arguments: list[str]) -> int:
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        return main(arguments)


class LanguageCommandTests(unittest.TestCase):
    def test_defaults_to_english_and_updates_each_setting_independently(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            self.assertEqual(run_silently(["setup", str(project)]), 0)

            with working_directory(project):
                self.assertEqual(run_silently(["init"]), 0)
                index_before = (project / ".silobrief" / "index.json").read_bytes()
                stdout = io.StringIO()
                with contextlib.redirect_stdout(stdout):
                    self.assertEqual(main(["language"]), 0)
                self.assertEqual(stdout.getvalue(), "CLI language: en\nBrief language: en\n")

                self.assertEqual(run_silently(["language", "--brief", "ko"]), 0)
                self.assertEqual(
                    load_language_settings(project),
                    {
                        "brief_language": "ko",
                        "cli_language": "en",
                        "settings_version": 1,
                    },
                )
                self.assertEqual((project / ".silobrief" / "index.json").read_bytes(), index_before)

                stdout = io.StringIO()
                with contextlib.redirect_stdout(stdout):
                    self.assertEqual(main(["language", "--cli", "ko"]), 0)
                self.assertEqual(stdout.getvalue(), "CLI 언어: ko\n브리프 언어: ko\n")
                self.assertEqual(
                    load_language_settings(project),
                    {
                        "brief_language": "ko",
                        "cli_language": "ko",
                        "settings_version": 1,
                    },
                )

    def test_existing_project_without_language_file_uses_english_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            self.assertEqual(run_silently(["setup", str(project)]), 0)
            language_path = project / ".silobrief" / "language.json"
            language_path.unlink()

            with working_directory(project):
                self.assertEqual(
                    load_language_settings(project),
                    {
                        "brief_language": "en",
                        "cli_language": "en",
                        "settings_version": 1,
                    },
                )
                self.assertEqual(run_silently(["init"]), 0)

            self.assertFalse(language_path.exists())

    def test_rejects_an_invalid_persisted_language(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            self.assertEqual(run_silently(["setup", str(project)]), 0)
            language_path = project / ".silobrief" / "language.json"
            value = json.loads(language_path.read_text(encoding="utf-8"))
            value["brief_language"] = "ja"
            language_path.write_text(json.dumps(value), encoding="utf-8")

            with self.assertRaisesRegex(SetupError, "languages must be en or ko"):
                load_language_settings(project)

    def test_korean_cli_setting_changes_help_and_search_output_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            source = project / "service.py"
            source.write_text("def retry_request():\n    return None\n", encoding="utf-8")
            self.assertEqual(run_silently(["setup", str(project)]), 0)

            with working_directory(project):
                self.assertEqual(run_silently(["language", "--cli", "ko"]), 0)
                self.assertEqual(run_silently(["init"]), 0)

                stdout = io.StringIO()
                with contextlib.redirect_stdout(stdout):
                    self.assertEqual(main(["search", "retry request"]), 0)
                self.assertTrue(stdout.getvalue().startswith("코드 후보:\n"))

                stdout = io.StringIO()
                with contextlib.redirect_stdout(stdout), self.assertRaises(SystemExit) as caught:
                    main(["--help"])
                self.assertEqual(caught.exception.code, 0)
                self.assertIn("검토된 작업 브리프", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
