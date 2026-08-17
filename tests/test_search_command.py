from __future__ import annotations

import contextlib
import hashlib
import io
import tempfile
import unittest
from pathlib import Path

from silobrief.cli import main
from tests.test_chat_command import prepare_project, working_directory


def project_digest(project: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in project.rglob("*") if item.is_file()):
        digest.update(path.relative_to(project).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
    return digest.hexdigest()


class SearchCommandTests(unittest.TestCase):
    def test_prints_explainable_candidates_without_writing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            prepare_project(project)
            before = project_digest(project)

            first_stdout = io.StringIO()
            first_stderr = io.StringIO()
            with (
                working_directory(project),
                contextlib.redirect_stdout(first_stdout),
                contextlib.redirect_stderr(first_stderr),
            ):
                first_result = main(["search", "run delivery with urllib3"])

            second_stdout = io.StringIO()
            second_stderr = io.StringIO()
            with (
                working_directory(project),
                contextlib.redirect_stdout(second_stdout),
                contextlib.redirect_stderr(second_stderr),
            ):
                second_result = main(["search", "run delivery with urllib3"])

            self.assertEqual((first_result, second_result), (0, 0))
            self.assertEqual(first_stderr.getvalue(), "")
            self.assertEqual(second_stderr.getvalue(), "")
            self.assertEqual(first_stdout.getvalue(), second_stdout.getvalue())
            self.assertEqual(project_digest(project), before)

            output = first_stdout.getvalue()
            self.assertIn("Candidates:\n", output)
            self.assertIn("[1] function run", output)
            self.assertIn("File: package/service.py", output)
            self.assertIn('name contains "run"', output)
            self.assertIn('import contains "delivery, urllib3"', output)
            self.assertIn("Relevance:", output)
            self.assertNotIn("private-boundary-canary", output)

    def test_rejects_empty_prompt(self) -> None:
        stderr = io.StringIO()

        with contextlib.redirect_stderr(stderr), self.assertRaises(SystemExit) as caught:
            main(["search", "   "])

        self.assertEqual(caught.exception.code, 2)
        self.assertIn("request must not be empty", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
