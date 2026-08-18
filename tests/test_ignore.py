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

            with (
                working_directory(project),
                mock.patch(
                    "silobrief.boundaries.save_config",
                    side_effect=SetupError("write failed"),
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
                    "silobrief.state.tempfile.mkstemp",
                    side_effect=OSError("temporary file unavailable"),
                ),
            ):
                self.assert_ignore_error(["private.py", "--as", "Private"])

            self.assertEqual(state_snapshot(project), before)
