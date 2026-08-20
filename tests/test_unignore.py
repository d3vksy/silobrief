from __future__ import annotations

import contextlib
import io
import json
import os
import stat
import tempfile
import threading
import unittest
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import cast
from unittest import mock

import silobrief.boundaries as boundary_commands
import silobrief.state as state_module
from silobrief.cli import main
from silobrief.state import BoundaryData, ConfigData, SetupError


@contextlib.contextmanager
def working_directory(path: Path) -> Iterator[None]:
    previous = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous)


def boundaries(project: Path) -> list[BoundaryData]:
    value: object = json.loads((project / ".silobrief" / "config.json").read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise AssertionError("config must be an object")
    raw = value.get("boundaries")
    if not isinstance(raw, list):
        raise AssertionError("boundaries must be an array")
    return cast(list[BoundaryData], raw)


def state_snapshot(project: Path) -> dict[str, tuple[bytes, int, int]]:
    state = project / ".silobrief"
    result: dict[str, tuple[bytes, int, int]] = {}
    for name in ("config.json", "index.json"):
        path = state / name
        if path.is_file():
            metadata = path.stat()
            result[name] = (
                path.read_bytes(),
                metadata.st_mtime_ns,
                stat.S_IMODE(metadata.st_mode),
            )
    return result


def run_silently(arguments: list[str]) -> int:
    with (
        contextlib.redirect_stdout(io.StringIO()),
        contextlib.redirect_stderr(io.StringIO()),
    ):
        return main(arguments)


class UnignoreCommandTests(unittest.TestCase):
    def assert_unignore_error(self, selector: str) -> str:
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr), self.assertRaises(SystemExit) as caught:
            main(["unignore", selector])
        self.assertEqual(caught.exception.code, 2)
        message = stderr.getvalue()
        self.assertNotIn("invalid choice", message)
        return message

    def test_removes_boundary_by_path_without_requiring_the_target(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            private = project / "private"
            private.mkdir()
            (private / "secret.py").write_text("SECRET = True\n", encoding="utf-8")
            self.assertEqual(run_silently(["setup", str(project)]), 0)
            with working_directory(project):
                self.assertEqual(
                    run_silently(
                        [
                            "ignore",
                            "private",
                            "--as",
                            "Private adapter",
                            "--alias",
                            "private-boundary",
                        ]
                    ),
                    0,
                )
                self.assertEqual(run_silently(["init"]), 0)

            (private / "secret.py").unlink()
            private.rmdir()
            stdout = io.StringIO()
            with working_directory(project), contextlib.redirect_stdout(stdout):
                self.assertEqual(main(["unignore", "private"]), 0)

            self.assertEqual(boundaries(project), [])
            index: object = json.loads(
                (project / ".silobrief" / "index.json").read_text(encoding="utf-8")
            )
            self.assertIsInstance(index, dict)
            self.assertIs(cast(dict[str, object], index).get("stale"), True)
            self.assertIn("private-boundary", stdout.getvalue())
            self.assertIn("private", stdout.getvalue())
            self.assertIn("sb init", stdout.getvalue())

    def test_removes_only_the_boundary_selected_by_alias(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            for name in ("first.py", "second.py"):
                (project / name).write_text("VALUE = 1\n", encoding="utf-8")
            self.assertEqual(run_silently(["setup", str(project)]), 0)
            with working_directory(project):
                self.assertEqual(
                    run_silently(
                        ["ignore", "first.py", "--as", "First", "--alias", "first-boundary"]
                    ),
                    0,
                )
                self.assertEqual(
                    run_silently(
                        [
                            "ignore",
                            "second.py",
                            "--as",
                            "Second",
                            "--alias",
                            "second-boundary",
                        ]
                    ),
                    0,
                )
                self.assertEqual(run_silently(["init"]), 0)
                self.assertEqual(run_silently(["unignore", "first-boundary"]), 0)

            self.assertEqual(
                boundaries(project),
                [
                    {
                        "alias": "second-boundary",
                        "description": "Second",
                        "path": "second.py",
                    }
                ],
            )

    def test_rejects_unknown_default_empty_and_ambiguous_selectors(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            (project / "shared").mkdir()
            (project / "other").mkdir()
            self.assertEqual(run_silently(["setup", str(project)]), 0)
            with working_directory(project):
                self.assertEqual(
                    run_silently(["ignore", "shared", "--as", "Shared path", "--alias", "first"]),
                    0,
                )
                self.assertEqual(
                    run_silently(["ignore", "other", "--as", "Other path", "--alias", "shared"]),
                    0,
                )
                self.assertEqual(run_silently(["init"]), 0)
                before = state_snapshot(project)
                for selector in ("missing", ".git/", "", "shared"):
                    with self.subTest(selector=selector):
                        self.assert_unignore_error(selector)
                        self.assertEqual(state_snapshot(project), before)

    def test_stale_index_blocks_chat_until_reinitialized(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            (project / "public.py").write_text("def run():\n    return 1\n", encoding="utf-8")
            (project / "private.py").write_text("PRIVATE = True\n", encoding="utf-8")
            self.assertEqual(run_silently(["setup", str(project)]), 0)
            with working_directory(project):
                self.assertEqual(
                    run_silently(
                        [
                            "ignore",
                            "private.py",
                            "--as",
                            "Private module",
                            "--alias",
                            "private-boundary",
                        ]
                    ),
                    0,
                )
                self.assertEqual(run_silently(["init"]), 0)
                self.assertEqual(run_silently(["unignore", "private-boundary"]), 0)
                stderr = io.StringIO()
                with contextlib.redirect_stderr(stderr):
                    result = main(
                        [
                            "chat",
                            "Review run",
                            "--out",
                            ".silobrief/exports/brief.md",
                        ]
                    )
                self.assertEqual(result, 4)
                self.assertIn("index is stale; run sb init", stderr.getvalue())
                self.assertFalse((project / ".silobrief" / "exports" / "brief.md").exists())
                self.assertEqual(run_silently(["init"]), 0)

    def test_preserves_state_when_index_or_config_update_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            (project / "private.py").write_text("PRIVATE = True\n", encoding="utf-8")
            self.assertEqual(run_silently(["setup", str(project)]), 0)
            with working_directory(project):
                self.assertEqual(
                    run_silently(
                        [
                            "ignore",
                            "private.py",
                            "--as",
                            "Private module",
                            "--alias",
                            "private-boundary",
                        ]
                    ),
                    0,
                )
                self.assertEqual(run_silently(["init"]), 0)
                before = state_snapshot(project)
                with (
                    self.subTest(function="mark_index_stale"),
                    mock.patch.object(
                        state_module,
                        "_mark_index_stale_in_state",
                        side_effect=SetupError("write failed"),
                    ),
                ):
                    self.assert_unignore_error("private-boundary")
                    self.assertEqual(state_snapshot(project), before)

                original_write = state_module._write_bytes_in_state

                def fail_config_write(
                    path: Path,
                    content: bytes,
                    state_descriptor: int | None,
                    *,
                    expected_current: state_module._FileVersion | None = None,
                ) -> tuple[int, int]:
                    if path.name == "config.json":
                        raise SetupError("write failed")
                    return original_write(
                        path,
                        content,
                        state_descriptor,
                        expected_current=expected_current,
                    )

                with (
                    self.subTest(function="save_config"),
                    mock.patch.object(
                        state_module,
                        "_write_bytes_in_state",
                        side_effect=fail_config_write,
                    ),
                ):
                    self.assert_unignore_error("private-boundary")
                    self.assertEqual(state_snapshot(project), before)

    def test_same_state_produces_identical_config_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            results: list[bytes] = []
            for name in ("first", "second"):
                project = root / name
                project.mkdir()
                (project / "private.py").write_text("PRIVATE = True\n", encoding="utf-8")
                self.assertEqual(run_silently(["setup", str(project)]), 0)
                with working_directory(project):
                    self.assertEqual(
                        run_silently(
                            [
                                "ignore",
                                "private.py",
                                "--as",
                                "Private module",
                                "--alias",
                                "private-boundary",
                            ]
                        ),
                        0,
                    )
                    self.assertEqual(run_silently(["unignore", "private-boundary"]), 0)
                results.append((project / ".silobrief" / "config.json").read_bytes())

            self.assertEqual(results[0], results[1])

    def test_requires_initialized_project(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            with working_directory(project):
                message = self.assert_unignore_error("private-boundary")
            self.assertIn("run sb setup first", message)

    def test_parallel_registration_and_removal_use_the_latest_config(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            for name in ("first.py", "second.py"):
                (project / name).write_text("PRIVATE = True\n", encoding="utf-8")
            self.assertEqual(run_silently(["setup", str(project)]), 0)
            boundary_commands.register_boundary(
                "first.py",
                "First",
                "first-boundary",
                start=project,
            )
            original_load = state_module._load_config_for_update
            both_loaded = threading.Barrier(2)

            def coordinated_load(
                state: Path,
                state_descriptor: int | None,
            ) -> tuple[ConfigData, state_module._FileSnapshot]:
                loaded = original_load(state, state_descriptor)
                try:
                    both_loaded.wait(timeout=0.25)
                except threading.BrokenBarrierError:
                    pass
                return loaded

            with (
                mock.patch.object(
                    state_module,
                    "_load_config_for_update",
                    side_effect=coordinated_load,
                ),
                ThreadPoolExecutor(max_workers=2) as executor,
            ):
                add = executor.submit(
                    boundary_commands.register_boundary,
                    "second.py",
                    "Second",
                    "second-boundary",
                    start=project,
                )
                remove = executor.submit(
                    boundary_commands.unregister_boundary,
                    "first-boundary",
                    start=project,
                )
                self.assertTrue(add.result(timeout=5).changed)
                self.assertEqual(remove.result(timeout=5)["alias"], "first-boundary")

            self.assertEqual(
                boundaries(project),
                [
                    {
                        "alias": "second-boundary",
                        "description": "Second",
                        "path": "second.py",
                    }
                ],
            )
