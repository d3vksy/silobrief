from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import sys
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
from silobrief.state import ConfigData, SetupError
from tests.windows_junctions import directory_junction


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


def state_snapshot(project: Path) -> dict[str, tuple[bytes, int]]:
    state = project / ".silobrief"
    result: dict[str, tuple[bytes, int]] = {}
    for name in ("config.json", "index.json"):
        path = state / name
        if path.is_file():
            result[name] = (path.read_bytes(), path.stat().st_mtime_ns)
    return result


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
            source_digest = hashlib.sha256(private_file.read_bytes()).digest()
            self.assertEqual(main(["setup", str(project)]), 0)
            stdout = io.StringIO()

            with working_directory(project), contextlib.redirect_stdout(stdout):
                result = main(
                    [
                        "ignore",
                        "private_adapter.py",
                        "--as",
                        " Private service adapter ",
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
                        "description": " Private service adapter ",
                        "path": "private_adapter.py",
                    }
                ],
            )
            self.assertIn("internal-adapter", stdout.getvalue())
            self.assertIn("private_adapter.py", stdout.getvalue())
            self.assertEqual(hashlib.sha256(private_file.read_bytes()).digest(), source_digest)

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

    def test_ignore_normalizes_windows_separators(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            private_file = project / "package" / "private.py"
            private_file.parent.mkdir()
            private_file.write_text("pass\n", encoding="utf-8", newline="\n")
            self.assertEqual(main(["setup", str(project)]), 0)

            with working_directory(project), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(
                    main(["ignore", r"package\private.py", "--as", "Private module"]),
                    0,
                )

            boundaries = read_config(project)["boundaries"]
            if not isinstance(boundaries, list) or not boundaries:
                self.fail("boundary was not stored")
            boundary = boundaries[0]
            if not isinstance(boundary, dict):
                self.fail("boundary must be an object")
            self.assertEqual(boundary.get("path"), "package/private.py")

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

    def test_ignore_rejects_absolute_parent_and_mixed_separator_paths(self) -> None:
        path_cases = {
            "empty": "",
            "native-absolute": None,
            "posix-absolute": "/outside/private.py",
            "windows-absolute": r"C:\outside\private.py",
            "windows-drive-relative": r"C:private.py",
            "unc": r"\\server\share\private.py",
            "parent-posix": "../outside.py",
            "parent-windows": r"..\outside.py",
            "mixed-parent": r"folder/..\outside.py",
        }

        for name, configured_path in path_cases.items():
            with self.subTest(case=name), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                project = root / "project"
                project.mkdir()
                outside = root / "outside.py"
                outside.write_text("OUTSIDE = True\n", encoding="utf-8", newline="\n")
                private_file = project / "private.py"
                private_file.write_text("pass\n", encoding="utf-8", newline="\n")
                self.assertEqual(main(["setup", str(project)]), 0)
                index = project / ".silobrief" / "index.json"
                index.write_text('{"index_version": 1, "stale": false}\n', encoding="utf-8")
                before = state_snapshot(project)
                path_text = (
                    str(private_file.resolve()) if configured_path is None else configured_path
                )

                with working_directory(project):
                    self.assert_ignore_error([path_text, "--as", "Must fail"])

                self.assertEqual(state_snapshot(project), before)

    def test_ignore_rejects_missing_path_and_invalid_text_fields(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            private_file = project / "private.py"
            private_file.write_text("pass\n", encoding="utf-8", newline="\n")
            self.assertEqual(main(["setup", str(project)]), 0)
            before = state_snapshot(project)
            cases = [
                ["missing.py", "--as", "Missing"],
                ["private.py", "--as", ""],
                ["private.py", "--as", " \t"],
                ["private.py", "--as", "Private", "--alias", ""],
                ["private.py", "--as", "Private", "--alias", "UPPER"],
                ["private.py", "--as", "Private", "--alias", "under_score"],
                ["private.py", "--as", "Private", "--alias", "a" * 41],
                ["private.py", "--as", "Private", "--alias", "경계"],
            ]

            with working_directory(project):
                for arguments in cases:
                    with self.subTest(arguments=arguments):
                        self.assert_ignore_error(arguments)
                        self.assertEqual(state_snapshot(project), before)

    def test_ignore_requires_initialized_project(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            (project / "private.py").write_text("pass\n", encoding="utf-8", newline="\n")

            with working_directory(project):
                message = self.assert_ignore_error(["private.py", "--as", "Private"])

            self.assertIn("run sb setup first", message)
            self.assertFalse((project / ".silobrief").exists())

    def test_ignore_rejects_duplicate_alias_and_skips_auto_alias_collision(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            for name in ("one.py", "two.py", "three.py"):
                (project / name).write_text("pass\n", encoding="utf-8", newline="\n")
            self.assertEqual(main(["setup", str(project)]), 0)

            with working_directory(project), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(
                    main(["ignore", "one.py", "--as", "One", "--alias", "boundary-2"]),
                    0,
                )
            before = state_snapshot(project)

            with working_directory(project):
                self.assert_ignore_error(["two.py", "--as", "Two", "--alias", "boundary-2"])
            self.assertEqual(state_snapshot(project), before)

            with working_directory(project), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(["ignore", "three.py", "--as", "Three"]), 0)
            boundaries = read_config(project)["boundaries"]
            if not isinstance(boundaries, list) or len(boundaries) != 2:
                self.fail("boundaries must contain two entries")
            second = boundaries[1]
            if not isinstance(second, dict):
                self.fail("boundary must be an object")
            self.assertEqual(second.get("alias"), "boundary-3")

    def test_ignore_rejects_symlink_target_and_component(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project"
            project.mkdir()
            actual = project / "actual"
            actual.mkdir()
            (actual / "private.py").write_text("pass\n", encoding="utf-8", newline="\n")
            outside = root / "outside"
            outside.mkdir()
            self.assertEqual(main(["setup", str(project)]), 0)
            direct_link = project / "private-link.py"
            component_link = project / "directory-link"
            outside_link = project / "outside-link"
            try:
                direct_link.symlink_to(actual / "private.py")
                component_link.symlink_to(actual, target_is_directory=True)
                outside_link.symlink_to(outside, target_is_directory=True)
            except OSError as error:
                self.skipTest(f"symbolic links unavailable: {error}")
            before = state_snapshot(project)

            with working_directory(project):
                for path_text in (
                    "private-link.py",
                    "directory-link/private.py",
                    "outside-link",
                ):
                    with self.subTest(path=path_text):
                        self.assert_ignore_error([path_text, "--as", "Must fail"])
                        self.assertEqual(state_snapshot(project), before)

    @unittest.skipUnless(os.name == "nt", "directory junctions require Windows")
    def test_ignore_rejects_a_directory_junction_component(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "project"
            actual = project / "actual"
            actual.mkdir(parents=True)
            (actual / "private.py").write_text("pass\n", encoding="utf-8")
            self.assertEqual(main(["setup", str(project)]), 0)
            before = state_snapshot(project)

            with directory_junction(project / "linked", actual), working_directory(project):
                self.assert_ignore_error(["linked/private.py", "--as", "Must fail"])

            self.assertEqual(state_snapshot(project), before)

    @unittest.skipUnless(os.name == "nt", "directory junctions require Windows")
    def test_ignore_keeps_state_parent_locked_during_atomic_save(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project"
            project.mkdir()
            private = project / "private.py"
            private.write_text("pass\n", encoding="utf-8", newline="\n")
            self.assertEqual(main(["setup", str(project)]), 0)
            state = project / ".silobrief"
            backup = project / ".silobrief-backup"
            outside = root / "outside"
            outside.mkdir()
            outside_config = outside / "config.json"
            outside_config.write_bytes(b"OUTSIDE_CONFIG_CANARY\n")
            original_mkstemp = tempfile.mkstemp
            swap_blocked = False
            swapped = False

            try:
                with contextlib.ExitStack() as junctions:

                    def try_parent_swap(
                        suffix: str | None = None,
                        prefix: str | None = None,
                        dir: str | os.PathLike[str] | None = None,
                        text: bool = False,
                    ) -> tuple[int, str]:
                        nonlocal swap_blocked, swapped
                        if not swap_blocked and not swapped:
                            try:
                                state.rename(backup)
                            except OSError:
                                swap_blocked = True
                            else:
                                swapped = True
                                junctions.enter_context(directory_junction(state, outside))
                        return original_mkstemp(
                            suffix=suffix,
                            prefix=prefix,
                            dir=dir,
                            text=text,
                        )

                    with (
                        working_directory(project),
                        contextlib.redirect_stdout(io.StringIO()),
                        mock.patch(
                            "silobrief.state.tempfile.mkstemp",
                            side_effect=try_parent_swap,
                        ),
                    ):
                        self.assertEqual(
                            main(["ignore", "private.py", "--as", "Private module"]),
                            0,
                        )
            finally:
                if backup.exists():
                    backup.rename(state)

            self.assertTrue(swap_blocked)
            self.assertFalse(swapped)
            self.assertEqual(outside_config.read_bytes(), b"OUTSIDE_CONFIG_CANARY\n")
            self.assertEqual(
                read_config(project)["boundaries"],
                [
                    {
                        "alias": "boundary-1",
                        "description": "Private module",
                        "path": "private.py",
                    }
                ],
            )

    @unittest.skipUnless(os.name == "nt", "directory junctions require Windows")
    def test_state_save_rejects_a_replaced_project_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project"
            project.mkdir()
            self.assertTrue(state_module.setup_project(project))
            original_root = project.resolve(strict=True)
            config = state_module.load_config(original_root)
            backup = root / "project-original"
            outside = root / "outside"
            outside_state = outside / ".silobrief"
            outside_state.mkdir(parents=True)
            outside_config = outside_state / "config.json"
            outside_config.write_bytes(b"OUTSIDE_CONFIG_CANARY\n")

            project.rename(backup)
            try:
                with directory_junction(project, outside):
                    with self.assertRaises(SetupError):
                        state_module.save_config(original_root, config)
            finally:
                if backup.exists():
                    backup.rename(project)

            self.assertEqual(outside_config.read_bytes(), b"OUTSIDE_CONFIG_CANARY\n")

    def test_state_save_rejects_a_real_project_directory_swap(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project"
            replacement = root / "replacement"
            project.mkdir()
            replacement.mkdir()
            self.assertTrue(state_module.setup_project(project))
            self.assertTrue(state_module.setup_project(replacement))
            original_root = project.resolve(strict=True)
            config = state_module.load_config(original_root)
            config["boundaries"] = [
                {"alias": "private", "description": "Private", "path": "private.py"}
            ]
            replacement_config = replacement / ".silobrief" / "config.json"
            canary = replacement_config.read_bytes()
            backup = root / "project-original"
            swapped = False

            def swap_root() -> None:
                nonlocal swapped
                if not swapped:
                    project.rename(backup)
                    replacement.rename(project)
                    swapped = True

            if os.name == "nt":
                original_open = state_module._open_windows_directory

                def open_directory(path: Path) -> int:
                    if path == original_root:
                        swap_root()
                    return original_open(path)

                patcher = mock.patch.object(
                    state_module, "_open_windows_directory", side_effect=open_directory
                )
            else:
                original_open_posix = state_module._open_posix_directory

                def open_directory_posix(path: str | Path, *, dir_fd: int | None = None) -> int:
                    if dir_fd is None and Path(path) == original_root:
                        swap_root()
                    return original_open_posix(path, dir_fd=dir_fd)

                patcher = mock.patch.object(
                    state_module, "_open_posix_directory", side_effect=open_directory_posix
                )

            try:
                with patcher, self.assertRaises(SetupError):
                    state_module.save_config(original_root, config)
            finally:
                if swapped:
                    project.rename(replacement)
                    backup.rename(project)

            self.assertTrue(swapped)
            self.assertEqual(replacement_config.read_bytes(), canary)

    def test_state_save_rejects_a_real_state_directory_swap(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project"
            replacement = root / "replacement"
            project.mkdir()
            replacement.mkdir()
            self.assertTrue(state_module.setup_project(project))
            self.assertTrue(state_module.setup_project(replacement))
            project = project.resolve(strict=True)
            replacement = replacement.resolve(strict=True)
            state = project / ".silobrief"
            original_state = state.resolve(strict=True)
            replacement_state = replacement / ".silobrief"
            replacement_config = replacement_state / "config.json"
            canary = replacement_config.read_bytes()
            backup = project / ".silobrief-original"
            config = state_module.load_config(project)
            config["boundaries"] = [
                {"alias": "private", "description": "Private", "path": "private.py"}
            ]
            swapped = False

            def swap_state() -> None:
                nonlocal swapped
                if not swapped:
                    state.rename(backup)
                    replacement_state.rename(state)
                    swapped = True

            if os.name == "nt":
                original_open = state_module._open_windows_directory

                def open_directory(path: Path) -> int:
                    if path == original_state:
                        swap_state()
                    return original_open(path)

                patcher = mock.patch.object(
                    state_module, "_open_windows_directory", side_effect=open_directory
                )
            else:
                original_open_posix = state_module._open_posix_directory

                def open_directory_posix(path: str | Path, *, dir_fd: int | None = None) -> int:
                    if path == state_module.STATE_DIRECTORY and dir_fd is not None:
                        swap_state()
                    return original_open_posix(path, dir_fd=dir_fd)

                patcher = mock.patch.object(
                    state_module, "_open_posix_directory", side_effect=open_directory_posix
                )

            try:
                with patcher, self.assertRaises(SetupError):
                    state_module.save_config(project, config)
            finally:
                if swapped:
                    state.rename(replacement_state)
                    backup.rename(state)

            self.assertTrue(swapped)
            self.assertEqual(replacement_config.read_bytes(), canary)

    @unittest.skipIf(os.name == "nt", "dir-fd writes require POSIX")
    def test_state_save_creates_temporary_file_from_state_descriptor(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project"
            outside = root / "outside"
            project.mkdir()
            outside.mkdir()
            self.assertTrue(state_module.setup_project(project))
            config = state_module.load_config(project)
            config["boundaries"] = [
                {"alias": "private", "description": "Private", "path": "private.py"}
            ]
            state = project / ".silobrief"
            backup = project / ".silobrief-original"
            outside_config = outside / "config.json"
            outside_config.write_bytes(b"OUTSIDE_CONFIG_CANARY\n")
            original_create = state_module._create_temporary_file
            swapped = False

            def swap_before_create(path: Path, descriptor: int | None) -> tuple[int, str]:
                nonlocal swapped
                state.rename(backup)
                state.symlink_to(outside, target_is_directory=True)
                swapped = True
                return original_create(path, descriptor)

            try:
                with mock.patch(
                    "silobrief.state._create_temporary_file",
                    side_effect=swap_before_create,
                ):
                    with self.assertRaises(SetupError):
                        state_module.save_config(project, config)
            finally:
                if state.is_symlink():
                    state.unlink()
                if backup.exists():
                    backup.rename(state)

            self.assertTrue(swapped)
            self.assertEqual(outside_config.read_bytes(), b"OUTSIDE_CONFIG_CANARY\n")
            self.assertEqual(list(outside.glob(".config.json-*.tmp")), [])
            self.assertEqual(read_config(project)["boundaries"], config["boundaries"])

    def test_state_save_rejects_temporary_hardlink_substitution(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project"
            project.mkdir()
            self.assertTrue(state_module.setup_project(project))
            project = project.resolve(strict=True)
            target = project / ".silobrief" / "config.json"
            before = target.read_bytes()
            canary = root / "outside.json"
            canary.write_bytes(b"OUTSIDE_CONFIG_CANARY\n")
            config = state_module.load_config(project)
            config["boundaries"] = [
                {"alias": "private", "description": "Private", "path": "private.py"}
            ]
            original_verify = state_module._verify_temporary_entry
            verification_count = 0

            def substitute_before_second_check(
                path: Path,
                temporary_name: str,
                descriptor: int | None,
                expected_identity: tuple[int, int],
            ) -> None:
                nonlocal verification_count
                verification_count += 1
                if verification_count == 2:
                    if descriptor is None:
                        temporary = Path(temporary_name)
                        temporary.unlink()
                        os.link(canary, temporary)
                    else:
                        os.unlink(temporary_name, dir_fd=descriptor)
                        os.link(canary, temporary_name, dst_dir_fd=descriptor)
                original_verify(path, temporary_name, descriptor, expected_identity)

            with (
                mock.patch.object(
                    state_module,
                    "_verify_temporary_entry",
                    side_effect=substitute_before_second_check,
                ),
                self.assertRaises(SetupError),
            ):
                state_module.save_config(project, config)

            self.assertEqual(verification_count, 2)
            self.assertEqual(target.read_bytes(), before)
            self.assertEqual(canary.read_bytes(), b"OUTSIDE_CONFIG_CANARY\n")

    def test_state_save_does_not_report_success_after_commit_substitution(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project"
            project.mkdir()
            self.assertTrue(state_module.setup_project(project))
            canary = root / "outside.json"
            canary.write_bytes(b"OUTSIDE_CONFIG_CANARY\n")
            config = state_module.load_config(project)
            config["boundaries"] = [
                {"alias": "private", "description": "Private", "path": "private.py"}
            ]
            original_replace = state_module._replace_temporary_entry

            def substitute_during_commit(
                path: Path,
                temporary_name: str,
                descriptor: int | None,
            ) -> None:
                if descriptor is None:
                    temporary = Path(temporary_name)
                    temporary.unlink()
                    os.link(canary, temporary)
                else:
                    os.unlink(temporary_name, dir_fd=descriptor)
                    os.link(canary, temporary_name, dst_dir_fd=descriptor)
                original_replace(path, temporary_name, descriptor)

            with (
                mock.patch.object(
                    state_module,
                    "_replace_temporary_entry",
                    side_effect=substitute_during_commit,
                ),
                self.assertRaises(SetupError),
            ):
                state_module.save_config(project, config)

            self.assertEqual(canary.read_bytes(), b"OUTSIDE_CONFIG_CANARY\n")

    def test_state_saves_reject_same_inode_content_mutation(self) -> None:
        def run_case(target_name: str) -> None:
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                project = root / "project"
                project.mkdir()
                self.assertTrue(state_module.setup_project(project))
                project = project.resolve(strict=True)
                original_replace = state_module._replace_temporary_entry
                mutation_kept_identity = False

                def mutate_during_commit(
                    path: Path,
                    temporary_name: str,
                    descriptor: int | None,
                ) -> None:
                    nonlocal mutation_kept_identity
                    if descriptor is None:
                        temporary = Path(temporary_name)
                        before = temporary.stat(follow_symlinks=False)
                        temporary.write_bytes(b"!" * before.st_size)
                        after = temporary.stat(follow_symlinks=False)
                    else:
                        before = os.stat(
                            temporary_name,
                            dir_fd=descriptor,
                            follow_symlinks=False,
                        )
                        handle = os.open(
                            temporary_name,
                            os.O_WRONLY | os.O_TRUNC,
                            dir_fd=descriptor,
                        )
                        try:
                            os.write(handle, b"!" * before.st_size)
                        finally:
                            os.close(handle)
                        after = os.stat(
                            temporary_name,
                            dir_fd=descriptor,
                            follow_symlinks=False,
                        )
                    mutation_kept_identity = (
                        before.st_dev,
                        before.st_ino,
                        before.st_nlink,
                    ) == (after.st_dev, after.st_ino, after.st_nlink)
                    original_replace(path, temporary_name, descriptor)

                with (
                    mock.patch.object(
                        state_module,
                        "_replace_temporary_entry",
                        side_effect=mutate_during_commit,
                    ),
                    self.assertRaises(SetupError),
                ):
                    if target_name == "config.json":
                        config = state_module.load_config(project)
                        config["boundaries"] = [
                            {
                                "alias": "private",
                                "description": "Private",
                                "path": "private.py",
                            }
                        ]
                        state_module.save_config(project, config)
                    else:
                        state_module.save_index(
                            project,
                            b'{"index_version": 1, "stale": false}\n',
                        )

                self.assertTrue(mutation_kept_identity)
                target = project / ".silobrief" / target_name
                self.assertTrue(target.read_bytes())
                self.assertEqual(set(target.read_bytes()), {ord("!")})

        for target_name in ("config.json", "index.json"):
            with self.subTest(target=target_name):
                run_case(target_name)

    def test_ignore_rejects_invalid_stored_boundary_schema(self) -> None:
        invalid_boundaries = [
            {"alias": "UPPER", "description": "Private", "path": "private.py"},
            {"alias": "private", "description": "   ", "path": "private.py"},
            {"alias": "private", "description": "Private", "path": "../private.py"},
        ]

        for boundary in invalid_boundaries:
            with self.subTest(boundary=boundary), tempfile.TemporaryDirectory() as directory:
                project = Path(directory)
                (project / "private.py").write_text("pass\n", encoding="utf-8", newline="\n")
                (project / "new.py").write_text("pass\n", encoding="utf-8", newline="\n")
                self.assertEqual(main(["setup", str(project)]), 0)
                config = project / ".silobrief" / "config.json"
                value = read_config(project)
                value["boundaries"] = [boundary]
                config.write_text(
                    json.dumps(value, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                    newline="\n",
                )
                before = state_snapshot(project)

                with working_directory(project):
                    self.assert_ignore_error(["new.py", "--as", "New"])

                self.assertEqual(state_snapshot(project), before)

    def test_ignore_restores_index_when_config_update_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            (project / "private.py").write_text("pass\n", encoding="utf-8", newline="\n")
            self.assertEqual(main(["setup", str(project)]), 0)
            index = project / ".silobrief" / "index.json"
            index.write_text('{"index_version": 1, "stale": false}\n', encoding="utf-8")
            fixed_time = 1_700_000_000_000_000_000
            os.utime(index, ns=(fixed_time, fixed_time))
            before = state_snapshot(project)
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
                working_directory(project),
                mock.patch.object(
                    state_module,
                    "_write_bytes_in_state",
                    side_effect=fail_config_write,
                ),
            ):
                self.assert_ignore_error(["private.py", "--as", "Private"])

            self.assertEqual(state_snapshot(project), before)

    def test_ignore_reports_temporary_file_failure_without_state_changes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            (project / "private.py").write_text("pass\n", encoding="utf-8", newline="\n")
            self.assertEqual(main(["setup", str(project)]), 0)
            before = state_snapshot(project)

            with (
                working_directory(project),
                mock.patch(
                    "silobrief.state._create_temporary_file",
                    side_effect=OSError("temporary file unavailable"),
                ),
            ):
                self.assert_ignore_error(["private.py", "--as", "Private"])

            self.assertEqual(state_snapshot(project), before)

    def test_parallel_registrations_preserve_both_boundaries(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            for name in ("first.py", "second.py"):
                (project / name).write_text("PRIVATE = True\n", encoding="utf-8")
            self.assertEqual(main(["setup", str(project)]), 0)
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
                futures = [
                    executor.submit(
                        boundary_commands.register_boundary,
                        name,
                        name,
                        None,
                        start=project,
                    )
                    for name in ("first.py", "second.py")
                ]
                results = [future.result(timeout=5) for future in futures]

            self.assertTrue(all(result.changed for result in results))
            stored = read_config(project)["boundaries"]
            if not isinstance(stored, list) or not all(isinstance(item, dict) for item in stored):
                self.fail("boundaries must be an object array")
            items = cast(list[dict[str, str]], stored)
            self.assertEqual(
                sorted(item["path"] for item in items),
                ["first.py", "second.py"],
            )
            self.assertEqual(
                {item["alias"] for item in items},
                {"boundary-1", "boundary-2"},
            )

    @unittest.skipUnless(os.name == "nt", "Windows byte-range lock test")
    def test_initializes_an_empty_config_lock_only_after_acquiring_it(self) -> None:
        if sys.platform != "win32":
            return
        import msvcrt

        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            self.assertEqual(main(["setup", str(project)]), 0)
            state = project / ".silobrief"
            lock_path = state / ".config.lock"
            lock_path.touch()
            blocker = os.open(lock_path, os.O_RDWR)
            lock_attempted = threading.Event()
            initialized = threading.Event()
            original_lock = boundary_commands._lock_descriptor
            original_initialize = boundary_commands._ensure_lock_byte

            def observed_lock(descriptor: int) -> None:
                lock_attempted.set()
                original_lock(descriptor)

            def observed_initialize(descriptor: int) -> None:
                initialized.set()
                original_initialize(descriptor)

            def acquire_lock() -> None:
                with boundary_commands._config_update_lock(state, None):
                    pass

            os.lseek(blocker, 0, os.SEEK_SET)
            msvcrt.locking(blocker, msvcrt.LK_NBLCK, 1)
            locked = True
            try:
                with (
                    mock.patch.object(
                        boundary_commands,
                        "_lock_descriptor",
                        side_effect=observed_lock,
                    ),
                    mock.patch.object(
                        boundary_commands,
                        "_ensure_lock_byte",
                        side_effect=observed_initialize,
                    ),
                    ThreadPoolExecutor(max_workers=1) as executor,
                ):
                    future = executor.submit(acquire_lock)
                    reached_lock = lock_attempted.wait(timeout=2)
                    initialized_while_locked = initialized.wait(timeout=0.1)
                    os.lseek(blocker, 0, os.SEEK_SET)
                    msvcrt.locking(blocker, msvcrt.LK_UNLCK, 1)
                    locked = False
                    future.result(timeout=5)
                self.assertTrue(reached_lock)
                self.assertFalse(initialized_while_locked)
                self.assertTrue(initialized.is_set())
                self.assertEqual(lock_path.read_bytes(), b"\0")
            finally:
                if locked:
                    os.lseek(blocker, 0, os.SEEK_SET)
                    msvcrt.locking(blocker, msvcrt.LK_UNLCK, 1)
                os.close(blocker)

    @unittest.skipIf(os.name == "nt", "Windows prevents renaming an open lock file")
    def test_replacing_the_lock_file_does_not_bypass_posix_serialization(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            for name in ("first.py", "second.py"):
                (project / name).write_text("PRIVATE = True\n", encoding="utf-8")
            self.assertEqual(main(["setup", str(project)]), 0)
            original_load = state_module._load_config_for_update
            first_loaded = threading.Event()
            release_first = threading.Event()
            second_loaded = threading.Event()
            calls = 0
            calls_lock = threading.Lock()

            def coordinated_load(
                state: Path,
                state_descriptor: int | None,
            ) -> tuple[ConfigData, state_module._FileSnapshot]:
                nonlocal calls
                loaded = original_load(state, state_descriptor)
                with calls_lock:
                    calls += 1
                    current_call = calls
                if current_call == 1:
                    first_loaded.set()
                    self.assertTrue(release_first.wait(timeout=5))
                else:
                    second_loaded.set()
                return loaded

            with (
                mock.patch.object(
                    state_module,
                    "_load_config_for_update",
                    side_effect=coordinated_load,
                ),
                ThreadPoolExecutor(max_workers=2) as executor,
            ):
                first = executor.submit(
                    boundary_commands.register_boundary,
                    "first.py",
                    "First",
                    "first-boundary",
                    start=project,
                )
                self.assertTrue(first_loaded.wait(timeout=5))
                lock = project / ".silobrief" / ".config.lock"
                lock.write_bytes(b"old")
                lock.replace(lock.with_suffix(".old"))
                lock.write_bytes(b"new")
                second = executor.submit(
                    boundary_commands.register_boundary,
                    "second.py",
                    "Second",
                    "second-boundary",
                    start=project,
                )
                self.assertFalse(second_loaded.wait(timeout=0.25))
                release_first.set()
                self.assertTrue(first.result(timeout=5).changed)
                self.assertTrue(second.result(timeout=5).changed)

            stored = read_config(project)["boundaries"]
            if not isinstance(stored, list) or not all(isinstance(item, dict) for item in stored):
                self.fail("boundaries must be an object array")
            items = cast(list[dict[str, str]], stored)
            self.assertEqual(
                sorted(item["path"] for item in items),
                ["first.py", "second.py"],
            )

    @unittest.skipIf(os.name == "nt", "Windows holds the state directory open")
    def test_replacing_the_state_directory_cannot_lose_the_new_lock_update(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project"
            replacement = root / "replacement"
            project.mkdir()
            replacement.mkdir()
            for name in ("first.py", "second.py"):
                (project / name).write_text("PRIVATE = True\n", encoding="utf-8")
            self.assertEqual(main(["setup", str(project)]), 0)
            self.assertEqual(main(["setup", str(replacement)]), 0)
            original_load = state_module._load_config_for_update
            first_loaded = threading.Event()
            release_first = threading.Event()
            calls = 0
            calls_lock = threading.Lock()

            def coordinated_load(
                state: Path,
                state_descriptor: int | None,
            ) -> tuple[ConfigData, state_module._FileSnapshot]:
                nonlocal calls
                loaded = original_load(state, state_descriptor)
                with calls_lock:
                    calls += 1
                    current_call = calls
                if current_call == 1:
                    first_loaded.set()
                    self.assertTrue(release_first.wait(timeout=5))
                return loaded

            state = project / ".silobrief"
            backup = project / ".silobrief-old"
            with (
                mock.patch.object(
                    state_module,
                    "_load_config_for_update",
                    side_effect=coordinated_load,
                ),
                ThreadPoolExecutor(max_workers=2) as executor,
            ):
                first = executor.submit(
                    boundary_commands.register_boundary,
                    "first.py",
                    "First",
                    "first-boundary",
                    start=project,
                )
                self.assertTrue(first_loaded.wait(timeout=5))
                state.rename(backup)
                (replacement / ".silobrief").rename(state)
                second = executor.submit(
                    boundary_commands.register_boundary,
                    "second.py",
                    "Second",
                    "second-boundary",
                    start=project,
                )
                self.assertTrue(second.result(timeout=5).changed)
                release_first.set()
                with self.assertRaises(SetupError):
                    first.result(timeout=5)

            self.assertEqual(
                read_config(project)["boundaries"],
                [
                    {
                        "alias": "second-boundary",
                        "description": "Second",
                        "path": "second.py",
                    }
                ],
            )

    def test_config_compare_and_swap_preserves_an_external_update(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            for name in ("private.py", "external.py"):
                (project / name).write_text("PRIVATE = True\n", encoding="utf-8")
            self.assertEqual(main(["setup", str(project)]), 0)
            index = project / ".silobrief" / "index.json"
            index.write_text('{"index_version": 1, "stale": false}\n', encoding="utf-8")
            external = ConfigData(
                boundaries=[
                    {
                        "alias": "external-boundary",
                        "description": "External",
                        "path": "external.py",
                    }
                ],
                default_excludes=list(state_module.DEFAULT_EXCLUDES),
                schema_version=1,
            )
            external_bytes = state_module._json_bytes(external)
            original_mark = state_module._mark_index_stale_in_state

            def replace_config_after_stale(
                state: Path,
                state_descriptor: int | None,
            ) -> tuple[state_module._FileSnapshot, state_module._FileVersion] | None:
                stale_write = original_mark(state, state_descriptor)
                (state / "config.json").write_bytes(external_bytes)
                return stale_write

            with mock.patch.object(
                state_module,
                "_mark_index_stale_in_state",
                side_effect=replace_config_after_stale,
            ):
                with self.assertRaises(SetupError):
                    boundary_commands.register_boundary(
                        "private.py",
                        "Private",
                        "private-boundary",
                        start=project,
                    )

            self.assertEqual((project / ".silobrief" / "config.json").read_bytes(), external_bytes)
            self.assertIs(json.loads(index.read_text(encoding="utf-8"))["stale"], True)
