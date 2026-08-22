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

    def test_creates_a_small_flask_project_without_initializing_silobrief(self) -> None:
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
                    ".gitignore",
                    "README.md",
                    "app.py",
                    "private/jwt.py",
                    "requirements.txt",
                },
            )

            completed = subprocess.run(
                [sys.executable, "-m", "py_compile", "app.py", "private/jwt.py"],
                cwd=project,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

            behavior_script = """
import app

app.init_db()
client = app.app.test_client()
signup = client.post("/signup", json={"username": "minsu", "password": "1234"})
login = client.post("/login", json={"username": "minsu", "password": "1234"})
denied = client.post("/login", json={"username": "minsu", "password": "wrong"})
assert signup.status_code == 201
assert login.status_code == 200
assert login.get_json() == {"message": "로그인 성공"}
assert denied.status_code == 401
"""
            behavior = subprocess.run(
                [sys.executable, "-c", behavior_script],
                cwd=project,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(behavior.returncode, 0, behavior.stdout + behavior.stderr)

            readme = (project / "README.md").read_text(encoding="utf-8")
            for expected in (
                "Flask",
                "sb setup .",
                "sb language --cli ko --brief ko",
                'sb ignore private --as "JWT 설정"',
                "sb init",
                "sb log",
                "sb search",
                "sb brief",
                "/file",
                "/func",
                "로그인 성공 응답",
                ".silobrief/exports/brief.md",
            ):
                self.assertIn(expected, readme)

            app_source = (project / "app.py").read_text(encoding="utf-8")
            self.assertIn('@app.post("/signup")', app_source)
            self.assertIn('@app.post("/login")', app_source)
            self.assertIn("sqlite3.connect(DATABASE_PATH)", app_source)
            self.assertIn("generate_password_hash(password)", app_source)
            self.assertIn("check_password_hash(user[1], password)", app_source)
            self.assertNotIn("jwt.encode", app_source)
            self.assertEqual((project / ".gitignore").read_text(encoding="utf-8"), "users.db\n")

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

    def test_flask_task_reaches_a_single_brief_through_the_public_workflow(self) -> None:
        prompt = (
            "requirements.txt에 PyJWT를 추가하고 로그인 성공 시 1시간짜리 access_token을 "
            "반환해줘. 토큰의 사용자 정보는 user_id와 username만 포함하고, 비밀번호와 "
            "private 설정은 노출하지 마. diff와 테스트를 작성해줘."
        )
        review_input = "y\n\napp.py\n2\n\n\ny\ny\ny\ny\ny\ny\nWRITE\n"
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "practice"
            self.assertEqual(main(["example", str(project)]), 0)

            with working_directory(project):
                self.assertEqual(main(["setup", "."]), 0)
                self.assertEqual(main(["ignore", "private", "--as", "JWT 설정"]), 0)
                self.assertEqual(main(["init"]), 0)
                self.assertEqual(
                    main(
                        [
                            "log",
                            "app.py",
                            "--comment",
                            "JWT 서명 키는 private.jwt의 JWT_SECRET을 사용합니다.",
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
                            "brief",
                            prompt,
                        ]
                    )

            brief = project / ".silobrief/exports/brief.md"
            self.assertEqual(result, 0, stdout.getvalue() + stderr.getvalue())
            self.assertEqual(stderr.getvalue(), "")
            self.assertTrue(brief.is_file())
            content = brief.read_text(encoding="utf-8")
            self.assertIn(prompt, content)
            self.assertIn("function: login", content)
            self.assertIn("def login(", content)
            self.assertIn("source_delivery: embedded", content)
            self.assertNotIn("demo-only-change-me", content)
            self.assertFalse(brief.with_name("brief.sources.md").exists())

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
