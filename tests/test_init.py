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

import silobrief.sources as sources
from silobrief.cli import main
from silobrief.sources import SourceFile, SourceSnapshot


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


def source_bytes(project: Path) -> dict[str, bytes]:
    return {
        path.relative_to(project).as_posix(): path.read_bytes()
        for path in sorted(project.rglob("*.py"))
    }


def index_object(project: Path) -> dict[str, object]:
    value: object = json.loads((project / ".silobrief" / "index.json").read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise AssertionError("index must be a JSON object")
    return {str(key): item for key, item in value.items()}


class InitCommandTests(unittest.TestCase):
    def test_init_shows_tty_progress_without_changing_index_or_redirected_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            source = project / "service.py"
            source.write_text(
                "def run(value: int) -> int:\n    return value + 1\n",
                encoding="utf-8",
                newline="\n",
            )
            self.assertEqual(main(["setup", str(project)]), 0)

            tty_stderr = TtyBuffer()
            with (
                working_directory(project),
                contextlib.redirect_stdout(io.StringIO()),
                contextlib.redirect_stderr(tty_stderr),
            ):
                tty_result = main(["init"])
            tty_index = (project / ".silobrief" / "index.json").read_bytes()

            redirected_stderr = io.StringIO()
            with (
                working_directory(project),
                contextlib.redirect_stdout(io.StringIO()),
                contextlib.redirect_stderr(redirected_stderr),
            ):
                redirected_result = main(["init"])

            progress = tty_stderr.getvalue()
            self.assertEqual(tty_result, 0)
            self.assertEqual(redirected_result, 0)
            self.assertIn("\rsb init [--------------------]   0%", progress)
            self.assertIn("Analyzing 1 Python file", progress)
            self.assertIn("sb init [####################] 100%", progress)
            self.assertTrue(progress.rstrip().endswith("Indexed 1 Python file"), progress)
            self.assertEqual(redirected_stderr.getvalue(), "")
            self.assertEqual(
                (project / ".silobrief" / "index.json").read_bytes(),
                tty_index,
            )

    def test_init_finishes_tty_progress_line_before_an_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            (project / "broken.py").write_text("def broken(:\n", encoding="utf-8", newline="\n")
            self.assertEqual(main(["setup", str(project)]), 0)
            stderr = TtyBuffer()

            with working_directory(project), contextlib.redirect_stderr(stderr):
                result = main(["init"])

            output = stderr.getvalue()
            self.assertEqual(result, 3)
            self.assertIn("Analyzing 1 Python file", output)
            self.assertIn("\nsb: error: cannot parse broken.py", output)

    def test_init_localizes_tty_progress(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            (project / "service.py").write_text("VALUE = 1\n", encoding="utf-8", newline="\n")
            self.assertEqual(main(["setup", str(project)]), 0)
            stderr = TtyBuffer()

            with (
                working_directory(project),
                contextlib.redirect_stdout(io.StringIO()),
                contextlib.redirect_stderr(stderr),
            ):
                self.assertEqual(main(["language", "--cli", "ko"]), 0)
                result = main(["init"])

            output = stderr.getvalue()
            self.assertEqual(result, 0)
            self.assertIn("허용된 Python 파일 수집 중", output)
            self.assertIn("Python 파일 1개 색인 완료", output)

    def test_init_builds_a_deterministic_index_from_a_subdirectory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            package = project / "package"
            private = project / "private"
            package.mkdir()
            private.mkdir()
            service = package / "service.py"
            service.write_text(
                "from private.secret import send\n\n\ndef run():\n    send()\n",
                encoding="utf-8",
                newline="\n",
            )
            (private / "secret.py").write_text(
                "CANARY = 'fixture-private-canary'\n",
                encoding="utf-8",
                newline="\n",
            )
            self.assertEqual(main(["setup", str(project)]), 0)
            with working_directory(project), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(
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
                    0,
                )
            before_sources = source_bytes(project)

            first_stdout = io.StringIO()
            with working_directory(package), contextlib.redirect_stdout(first_stdout):
                first_result = main(["init"])
            first_index = (project / ".silobrief" / "index.json").read_bytes()

            with working_directory(project), contextlib.redirect_stdout(io.StringIO()):
                second_result = main(["init"])

            self.assertEqual(first_result, 0)
            self.assertEqual(second_result, 0)
            self.assertIn("index.json", first_stdout.getvalue())
            self.assertEqual((project / ".silobrief" / "index.json").read_bytes(), first_index)
            self.assertEqual(source_bytes(project), before_sources)
            self.assertNotIn(b"fixture-private-canary", first_index)
            self.assertIn(b"delivery-boundary", first_index)
            index = index_object(project)
            self.assertEqual(index["index_version"], 1)
            self.assertIs(index["stale"], False)

    def test_init_reports_parse_error_and_preserves_existing_index(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            source = project / "broken.py"
            source.write_text("def broken(:\n", encoding="utf-8", newline="\n")
            self.assertEqual(main(["setup", str(project)]), 0)
            index = project / ".silobrief" / "index.json"
            index.write_bytes(b'{"index_version": 1, "sentinel": true}\n')
            fixed_time = 1_700_000_000_000_000_000
            os.utime(index, ns=(fixed_time, fixed_time))
            before = (index.read_bytes(), index.stat().st_mtime_ns)
            stderr = io.StringIO()

            with working_directory(project), contextlib.redirect_stderr(stderr):
                result = main(["init"])

            self.assertEqual(result, 3)
            self.assertIn("broken.py", stderr.getvalue())
            self.assertIn("cannot parse", stderr.getvalue())
            self.assertEqual((index.read_bytes(), index.stat().st_mtime_ns), before)

    def test_init_detects_source_changes_before_replacing_index(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            source = project / "service.py"
            original = b"def run():\n    return 1\n"
            changed = b"def run():\n    return 2\n"
            source.write_bytes(original)
            self.assertEqual(main(["setup", str(project)]), 0)
            index = project / ".silobrief" / "index.json"
            index.write_bytes(b'{"index_version": 1, "sentinel": true}\n')
            fixed_time = 1_700_000_000_000_000_000
            os.utime(index, ns=(fixed_time, fixed_time))
            before_index = (index.read_bytes(), index.stat().st_mtime_ns)
            before = SourceSnapshot(
                files=(
                    SourceFile(
                        path="service.py",
                        content=original,
                        sha256=hashlib.sha256(original).hexdigest(),
                    ),
                ),
                warnings=(),
                digest="before",
            )
            after = SourceSnapshot(
                files=(
                    SourceFile(
                        path="service.py",
                        content=changed,
                        sha256=hashlib.sha256(changed).hexdigest(),
                    ),
                ),
                warnings=(),
                digest="after",
            )
            stderr = io.StringIO()

            with (
                working_directory(project),
                contextlib.redirect_stderr(stderr),
                mock.patch.object(sources, "snapshot_sources", side_effect=(before, after)),
            ):
                result = main(["init"])

            self.assertEqual(result, 4)
            self.assertIn("changed", stderr.getvalue())
            self.assertIn("service.py", stderr.getvalue())
            self.assertEqual((index.read_bytes(), index.stat().st_mtime_ns), before_index)
            self.assertEqual(source.read_bytes(), original)
