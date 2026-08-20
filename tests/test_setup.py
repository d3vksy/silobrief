from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import stat
import tempfile
import unittest
from collections.abc import Callable, Iterator
from pathlib import Path
from unittest import mock

import silobrief.state as state_module
from silobrief.cli import main
from tests.windows_junctions import directory_junction

DEFAULT_EXCLUDES = [
    ".git/",
    ".silobrief/",
    "__pycache__/",
    ".venv/",
    "venv/",
    "build/",
    "dist/",
]
SOURCE_DISCLOSURE_WARNING = (
    "warning: non-ignored Python files are analyzed locally; source excerpts you select and "
    "approve may be exported verbatim with comments, docstrings, strings, and internal "
    "identifiers. siloBrief does not detect secrets or provide security approval; review all "
    "output yourself.\n"
)


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
                "created .silobrief/config.json, .silobrief/notes.json, "
                ".silobrief/language.json, and .silobrief/exports/\n" + SOURCE_DISCLOSURE_WARNING,
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
            self.assertEqual(
                json.loads((state / "language.json").read_text(encoding="utf-8")),
                {
                    "brief_language": "en",
                    "cli_language": "en",
                    "settings_version": 1,
                },
            )
            self.assertTrue((state / "exports").is_dir())
            self.assertFalse((state / "index.json").exists())
            self.assertEqual(hashlib.sha256(source.read_bytes()).digest(), source_digest)
            if os.name != "nt":
                for name in ("config.json", "notes.json", "language.json"):
                    self.assertEqual(stat.S_IMODE((state / name).stat().st_mode), 0o600)
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
            tracked = [
                state / "config.json",
                state / "notes.json",
                state / "language.json",
                state / "exports",
            ]
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
            self.assertEqual(
                stdout.getvalue(),
                "validated existing .silobrief state\n" + SOURCE_DISCLOSURE_WARNING,
            )
            self.assertEqual(after, before)

    def test_v0_6_state_loads_without_migration_or_rewrite(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            (project / "service.py").write_text(
                "def run():\n    return 1\n",
                encoding="utf-8",
                newline="\n",
            )
            state = project / ".silobrief"
            state.mkdir()
            (state / "exports").mkdir()
            files = {
                "config.json": {
                    "boundaries": [],
                    "default_excludes": DEFAULT_EXCLUDES,
                    "schema_version": 1,
                },
                "notes.json": {
                    "notes": [
                        {
                            "comment": "v0.6 note",
                            "id": "note-" + "0" * 64,
                            "path": "service.py",
                        }
                    ],
                    "notes_version": 1,
                },
                "language.json": {
                    "brief_language": "ko",
                    "cli_language": "en",
                    "settings_version": 1,
                },
            }
            for name, value in files.items():
                (state / name).write_text(
                    json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                    newline="\n",
                )
            before = {name: (state / name).read_bytes() for name in files}

            self.assertEqual(main(["setup", str(project)]), 0)
            with working_directory(project):
                self.assertEqual(main(["init"]), 0)
                self.assertEqual(main(["search", "run"]), 0)

            self.assertEqual({name: (state / name).read_bytes() for name in files}, before)
            self.assertTrue((state / "index.json").is_file())

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

    @unittest.skipUnless(os.name == "nt", "directory junctions require Windows")
    def test_setup_rejects_project_and_state_directory_junctions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "target"
            target.mkdir()

            with directory_junction(root / "project-link", target) as project_link:
                message = self.assert_setup_error(project_link)
                self.assertIn("reparse point", message)
            self.assertFalse((target / ".silobrief").exists())

            state_source = root / "state-source"
            state_source.mkdir()
            self.assertEqual(main(["setup", str(state_source)]), 0)
            project = root / "project"
            project.mkdir()
            with directory_junction(project / ".silobrief", state_source / ".silobrief"):
                message = self.assert_setup_error(project)
                self.assertIn("real directory", message)

    @unittest.skipUnless(os.name == "nt", "directory junctions require Windows")
    def test_setup_locks_project_root_before_creating_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve(strict=True)
            project = root / "project"
            project.mkdir()
            state = project / ".silobrief"
            backup = root / "project-original"
            outside = root / "outside"
            outside_state = outside / ".silobrief"
            (outside_state / "exports").mkdir(parents=True)
            victim = outside_state / "victim.txt"
            victim.write_bytes(b"OUTSIDE_STATE_CANARY\n")
            original_mkdir = Path.mkdir
            swap_blocked = False
            swapped = False

            try:
                with contextlib.ExitStack() as junctions:

                    def try_project_swap(
                        self: Path,
                        mode: int = 0o777,
                        parents: bool = False,
                        exist_ok: bool = False,
                    ) -> None:
                        nonlocal swap_blocked, swapped
                        original_mkdir(self, mode=mode, parents=parents, exist_ok=exist_ok)
                        if self == state and not swap_blocked and not swapped:
                            try:
                                project.rename(backup)
                            except OSError:
                                swap_blocked = True
                            else:
                                swapped = True
                                junctions.enter_context(directory_junction(project, outside))

                    with (
                        contextlib.redirect_stdout(io.StringIO()),
                        mock.patch("pathlib.Path.mkdir", new=try_project_swap),
                    ):
                        self.assertEqual(main(["setup", str(project)]), 0)
            finally:
                if backup.exists():
                    backup.rename(project)

            self.assertTrue(swap_blocked)
            self.assertFalse(swapped)
            self.assertEqual(victim.read_bytes(), b"OUTSIDE_STATE_CANARY\n")

    def test_setup_does_not_clean_a_replaced_real_state_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve(strict=True)
            project = root / "project"
            replacement = root / "replacement"
            project.mkdir()
            replacement.mkdir()
            self.assertTrue(state_module.setup_project(replacement))
            state = project / ".silobrief"
            replacement_state = replacement / ".silobrief"
            replacement_config = replacement_state / "config.json"
            canary = replacement_config.read_bytes()
            backup = project / ".silobrief-original"
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
                    if path == state:
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
                with patcher, self.assertRaises(state_module.SetupError):
                    state_module.setup_project(project)
            finally:
                if swapped:
                    state.rename(replacement_state)
                    backup.rename(state)

            self.assertTrue(swapped)
            self.assertEqual(replacement_config.read_bytes(), canary)

    @unittest.skipIf(os.name == "nt", "dir-fd validation requires POSIX")
    def test_setup_validates_existing_files_from_the_open_state_directory(self) -> None:
        invalid_content = {
            "config.json": b"{}\n",
            "notes.json": b"{}\n",
            "language.json": b"{}\n",
            "index.json": b'{"index_version": 99}\n',
        }
        for entry_name in (*invalid_content, "exports"):
            with self.subTest(entry=entry_name), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                project = root / "project"
                replacement = root / "replacement"
                project.mkdir()
                replacement.mkdir()
                self.assertTrue(state_module.setup_project(project))
                self.assertTrue(state_module.setup_project(replacement))
                state = project / ".silobrief"
                replacement_state = replacement / ".silobrief"
                entry = state / entry_name
                if entry_name == "exports":
                    entry.rmdir()
                    entry.write_bytes(b"not a directory\n")
                else:
                    entry.write_bytes(invalid_content[entry_name])
                backup = project / ".silobrief-original"
                original_validate = state_module._validate_state
                swapped = False

                def validate_from_open_directory(
                    opened_state: Path,
                    descriptor: int | None = None,
                    *,
                    current_state: Path = state,
                    saved_state: Path = backup,
                    other_state: Path = replacement_state,
                    validate: Callable[
                        [Path, int | None], state_module.ConfigData
                    ] = original_validate,
                ) -> state_module.ConfigData:
                    nonlocal swapped
                    current_state.rename(saved_state)
                    other_state.rename(current_state)
                    swapped = True
                    try:
                        return validate(opened_state, descriptor)
                    finally:
                        current_state.rename(other_state)
                        saved_state.rename(current_state)

                with (
                    mock.patch.object(
                        state_module,
                        "_validate_state",
                        side_effect=validate_from_open_directory,
                    ),
                    self.assertRaises(state_module.SetupError),
                ):
                    state_module.setup_project(project)

                self.assertTrue(swapped)

    def test_setup_rejects_state_file_and_resumes_recognized_partial_state(self) -> None:
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

            self.assertTrue(state_module.setup_project(partial_project))
            self.assertEqual(partial_config.read_bytes(), config_before)
            self.assertTrue((partial_state / "notes.json").is_file())

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
            for version in (True, 4):
                with self.subTest(index_version=version):
                    content = json.dumps({"index_version": version}) + "\n"
                    index.write_text(content, encoding="utf-8")

                    self.assert_setup_error(project)
                    self.assertEqual(index.read_text(encoding="utf-8"), content)

    def test_setup_keeps_new_state_after_write_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)

            with mock.patch.object(
                state_module,
                "_publish_setup_entry",
                side_effect=OSError("disk full"),
            ):
                message = self.assert_setup_error(project)

            self.assertIn("cannot initialize", message)
            state = project / ".silobrief"
            self.assertTrue(state.is_dir())
            self.assertEqual({entry.name for entry in state.iterdir()}, {"exports"})
            self.assertTrue(state_module.setup_project(project))

    def test_setup_preserves_an_unrecognized_partial_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            state = project / ".silobrief"
            state.mkdir()
            canary = state / "other-process.txt"
            canary.write_bytes(b"OTHER_PROCESS_CANARY\n")

            with self.assertRaises(state_module.SetupError):
                state_module.setup_project(project)

            self.assertEqual(canary.read_bytes(), b"OTHER_PROCESS_CANARY\n")
            self.assertEqual({entry.name for entry in state.iterdir()}, {canary.name})

    def test_setup_preserves_and_rejects_an_unknown_setup_temp_name(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            state = project / ".silobrief"
            state.mkdir()
            stale = state / ".config.json-0123456789abcdef.tmp"
            stale.write_bytes(b"OTHER_PROCESS_CANARY\n")

            with self.assertRaises(state_module.SetupError):
                state_module.setup_project(project)

            self.assertEqual(stale.read_bytes(), b"OTHER_PROCESS_CANARY\n")
            self.assertEqual({entry.name for entry in state.iterdir()}, {stale.name})

    @unittest.skipIf(os.name == "nt", "POSIX setup files use mode 0600")
    def test_setup_rejects_a_permissive_partial_default_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            state = project / ".silobrief"
            (state / "exports").mkdir(parents=True)
            config = state / "config.json"
            config.write_bytes(dict(state_module._default_state_files())["config.json"])
            config.chmod(0o644)

            with self.assertRaises(state_module.SetupError):
                state_module.setup_project(project)

            self.assertEqual(stat.S_IMODE(config.stat().st_mode), 0o644)
            self.assertFalse((state / "notes.json").exists())

    def test_setup_resumes_after_each_published_entry_is_interrupted(self) -> None:
        for interrupted_entry in ("exports", "config.json", "language.json", "notes.json"):
            with self.subTest(entry=interrupted_entry), tempfile.TemporaryDirectory() as directory:
                project = Path(directory)
                state = project / ".silobrief"
                original_create = state_module._create_entry
                original_link = state_module._publish_temporary_entry

                def create_then_interrupt(
                    path: Path,
                    name: str,
                    descriptor: int | None,
                    *,
                    create: Callable[[Path, str, int | None], None] = original_create,
                    target: str = interrupted_entry,
                ) -> None:
                    create(path, name, descriptor)
                    if name == target:
                        raise KeyboardInterrupt

                def link_then_interrupt(
                    path: Path,
                    temporary_name: str,
                    descriptor: int | None,
                    source_descriptor: int,
                    *,
                    link: Callable[[Path, str, int | None, int], None] = original_link,
                    target: str = interrupted_entry,
                ) -> None:
                    link(path, temporary_name, descriptor, source_descriptor)
                    if path.name == target:
                        raise KeyboardInterrupt

                with (
                    mock.patch.object(
                        state_module,
                        "_create_entry",
                        side_effect=create_then_interrupt,
                    ),
                    mock.patch.object(
                        state_module,
                        "_publish_temporary_entry",
                        side_effect=link_then_interrupt,
                    ),
                    self.assertRaises(KeyboardInterrupt),
                ):
                    state_module.setup_project(project)

                self.assertTrue(state.is_dir())
                self.assertFalse(any(entry.name.endswith(".tmp") for entry in state.iterdir()))
                resumed = state_module.setup_project(project)
                self.assertEqual(resumed, interrupted_entry != "notes.json")
                self.assertFalse(state_module.setup_project(project))

    def test_setup_releases_temporary_resources_after_repeated_interrupts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            state = project / ".silobrief"
            descriptor_directory = Path("/proc/self/fd")
            descriptor_count = (
                len(list(descriptor_directory.iterdir())) if descriptor_directory.is_dir() else None
            )

            for attempt in range(100):
                with (
                    self.subTest(attempt=attempt),
                    mock.patch.object(
                        state_module,
                        "_temporary_file_identity",
                        side_effect=KeyboardInterrupt,
                    ),
                    self.assertRaises(KeyboardInterrupt),
                ):
                    state_module.setup_project(project)

                self.assertEqual({entry.name for entry in state.iterdir()}, {"exports"})
                moved = project / ".silobrief-moved"
                state.rename(moved)
                moved.rename(state)
                if descriptor_count is not None:
                    self.assertEqual(len(list(descriptor_directory.iterdir())), descriptor_count)

            self.assertTrue(state_module.setup_project(project))
            self.assertFalse(state_module.setup_project(project))

    def test_setup_releases_partial_state_validation_resources(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            state = project / ".silobrief"
            state.mkdir()
            (state / "exports").mkdir()
            config = state / "config.json"
            config.write_bytes(dict(state_module._default_state_files())["config.json"])
            if os.name != "nt":
                config.chmod(0o600)
            original_verify = state_module._verify_file_entry

            def interrupt_config_validation(
                path: Path,
                name: str,
                descriptor: int | None,
                expected_identity: tuple[int, int],
                label: str,
            ) -> None:
                if name == "config.json":
                    raise KeyboardInterrupt
                original_verify(path, name, descriptor, expected_identity, label)

            with (
                mock.patch.object(
                    state_module,
                    "_verify_file_entry",
                    side_effect=interrupt_config_validation,
                ),
                self.assertRaises(KeyboardInterrupt),
            ):
                state_module.setup_project(project)

            moved = project / ".silobrief-moved"
            state.rename(moved)
            moved.rename(state)
            self.assertTrue(state_module.setup_project(project))

    def test_setup_releases_exports_validation_resources(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            state = project / ".silobrief"
            (state / "exports").mkdir(parents=True)
            original_stat = state_module._entry_stat
            exports_checks = 0

            def interrupt_after_exports_scan(
                path: Path,
                name: str,
                descriptor: int | None,
            ) -> os.stat_result:
                nonlocal exports_checks
                result = original_stat(path, name, descriptor)
                if name == "exports":
                    exports_checks += 1
                    if exports_checks == 2:
                        raise KeyboardInterrupt
                return result

            with (
                mock.patch.object(
                    state_module,
                    "_entry_stat",
                    side_effect=interrupt_after_exports_scan,
                ),
                self.assertRaises(KeyboardInterrupt),
            ):
                state_module.setup_project(project)

            moved = project / ".silobrief-moved"
            state.rename(moved)
            moved.rename(state)
            self.assertTrue(state_module.setup_project(project))

    def test_setup_binds_incomplete_exports_validation_to_one_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory).resolve(strict=True)
            state = project / ".silobrief"
            exports = state / "exports"
            exports.mkdir(parents=True)
            canary = exports / "canary.txt"
            canary.write_bytes(b"OTHER_PROCESS_CANARY\n")
            backup = project / "exports-original"
            replacement = project / "exports-empty"
            replacement.mkdir()
            expected_identity = state_module._directory_identity(
                exports.stat(follow_symlinks=False)
            )
            original_listdir = os.listdir
            attempted = False
            swapped = False
            blocked = False

            def swap_exports_while_listing(path: os.PathLike[str] | int) -> list[str]:
                nonlocal attempted, blocked, swapped
                if isinstance(path, int):
                    try:
                        is_exports = (
                            state_module._directory_identity(os.fstat(path)) == expected_identity
                        )
                    except OSError:
                        is_exports = False
                else:
                    is_exports = Path(path) == exports
                if not is_exports or attempted:
                    return original_listdir(path)

                attempted = True
                try:
                    exports.rename(backup)
                    replacement.rename(exports)
                    swapped = True
                except OSError:
                    blocked = True
                try:
                    return original_listdir(path)
                finally:
                    if swapped:
                        exports.rename(replacement)
                        backup.rename(exports)

            with (
                mock.patch(
                    "silobrief.state.os.listdir",
                    side_effect=swap_exports_while_listing,
                ),
                self.assertRaises(state_module.SetupError),
            ):
                state_module.setup_project(project)

            self.assertTrue(attempted)
            self.assertTrue(swapped or blocked)
            self.assertEqual(canary.read_bytes(), b"OTHER_PROCESS_CANARY\n")

    @unittest.skipIf(os.name == "nt", "requires WSL on a Windows-mounted filesystem")
    def test_setup_fails_closed_on_a_windows_mounted_wsl_project(self) -> None:
        current = Path.cwd().resolve()
        if not current.as_posix().startswith("/mnt/"):
            self.skipTest("repository is not on a WSL Windows mount")

        with tempfile.TemporaryDirectory(dir=current) as directory:
            project = Path(directory)
            message = "native Windows.*WSL Linux filesystem"

            with self.assertRaisesRegex(state_module.SetupError, message):
                state_module.setup_project(project)
            with self.assertRaisesRegex(state_module.SetupError, message):
                state_module.setup_project(project)

            state = project / ".silobrief"
            self.assertEqual({entry.name for entry in state.iterdir()}, {"exports"})
            self.assertFalse((state / "config.json").exists())

    def test_setup_resumes_after_a_general_exception(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            original_link = state_module._publish_temporary_entry

            def fail_after_language(
                path: Path,
                temporary_name: str,
                descriptor: int | None,
                source_descriptor: int,
            ) -> None:
                original_link(path, temporary_name, descriptor, source_descriptor)
                if path.name == "language.json":
                    raise RuntimeError("injected failure")

            with (
                mock.patch.object(
                    state_module,
                    "_publish_temporary_entry",
                    side_effect=fail_after_language,
                ),
                self.assertRaisesRegex(RuntimeError, "injected failure"),
            ):
                state_module.setup_project(project)

            state = project / ".silobrief"
            self.assertEqual(
                {entry.name for entry in state.iterdir()},
                {"exports", "config.json", "language.json"},
            )
            self.assertTrue(state_module.setup_project(project))

    def test_setup_never_overwrites_a_concurrently_created_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            state = project / ".silobrief"
            canary = b"OTHER_PROCESS_CANARY\n"
            original_link = state_module._publish_temporary_entry
            injected = False

            def create_rival_then_link(
                path: Path,
                temporary_name: str,
                descriptor: int | None,
                source_descriptor: int,
            ) -> None:
                nonlocal injected
                if path.name == "config.json" and not injected:
                    injected = True
                    if descriptor is None:
                        path.write_bytes(canary)
                    else:
                        rival = os.open(
                            path.name,
                            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                            0o600,
                            dir_fd=descriptor,
                        )
                        try:
                            os.write(rival, canary)
                        finally:
                            os.close(rival)
                original_link(path, temporary_name, descriptor, source_descriptor)

            with (
                mock.patch.object(
                    state_module,
                    "_publish_temporary_entry",
                    side_effect=create_rival_then_link,
                ),
                self.assertRaises(state_module.SetupError),
            ):
                state_module.setup_project(project)

            config = state / "config.json"
            self.assertEqual(config.read_bytes(), canary)
            with self.assertRaises(state_module.SetupError):
                state_module.setup_project(project)
            self.assertEqual(config.read_bytes(), canary)
            self.assertEqual(
                {entry.name for entry in state.iterdir()},
                {"exports", "config.json"},
            )

    def test_setup_accepts_an_exact_concurrently_created_default(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            expected = dict(state_module._default_state_files())["config.json"]
            original_link = state_module._publish_temporary_entry
            injected = False

            def create_default_then_link(
                path: Path,
                temporary_name: str,
                descriptor: int | None,
                source_descriptor: int,
            ) -> None:
                nonlocal injected
                if path.name == "config.json" and not injected:
                    injected = True
                    if descriptor is None:
                        path.write_bytes(expected)
                    else:
                        rival = os.open(
                            path.name,
                            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                            0o600,
                            dir_fd=descriptor,
                        )
                        try:
                            os.write(rival, expected)
                        finally:
                            os.close(rival)
                original_link(path, temporary_name, descriptor, source_descriptor)

            with mock.patch.object(
                state_module,
                "_publish_temporary_entry",
                side_effect=create_default_then_link,
            ):
                self.assertTrue(state_module.setup_project(project))

            self.assertEqual((project / ".silobrief" / "config.json").read_bytes(), expected)
            self.assertFalse(state_module.setup_project(project))
