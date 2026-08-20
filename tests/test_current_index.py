from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from typing import cast
from unittest import mock

from silobrief import current_index
from silobrief.boundaries import register_boundary
from silobrief.current_index import (
    CurrentIndexError,
    load_current_index,
    load_current_index_for_approval,
    revalidate_current_index_approval,
)
from silobrief.index import config_digest
from silobrief.initialization import initialize_index
from silobrief.sources import SourceCollectionError, SourceWarning, snapshot_sources
from silobrief.state import STATE_DIRECTORY, SetupError, load_config, setup_project
from silobrief.stored_index import StoredIndexError, load_stored_index

V1_0_4_INDEX = Path(__file__).with_name("fixtures") / "index-v1.0.4-minimal.json"


def create_project(project: Path) -> tuple[Path, Path]:
    package = project / "package"
    private = project / "private"
    package.mkdir()
    private.mkdir()
    source = package / "service.py"
    source.write_text("def run():\n    return 1\n", encoding="utf-8", newline="\n")
    secret = private / "secret.py"
    secret.write_text("CANARY = 'private-canary'\n", encoding="utf-8", newline="\n")
    setup_project(project)
    register_boundary(
        "private",
        "External delivery adapter",
        "delivery-boundary",
        start=project,
    )
    initialize_index(project)
    return source, secret


def file_state(project: Path) -> dict[str, tuple[bytes, int]]:
    return {
        path.relative_to(project).as_posix(): (path.read_bytes(), path.stat().st_mtime_ns)
        for path in sorted(project.rglob("*"))
        if path.is_file()
    }


def object_file(path: Path) -> dict[str, object]:
    value: object = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise AssertionError("expected a JSON object")
    return cast(dict[str, object], value)


def write_object(path: Path, value: dict[str, object]) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


class CurrentIndexTests(unittest.TestCase):
    def assert_current_error(self, project: Path, expected: str) -> None:
        before = file_state(project)

        with self.assertRaises(CurrentIndexError) as caught:
            load_current_index(project)

        message = str(caught.exception)
        self.assertIn(expected, message)
        self.assertIn("run sb init", message)
        self.assertNotIn(str(project), message)
        self.assertNotIn("private-canary", message)
        self.assertEqual(file_state(project), before)

    def test_loads_current_index_and_returns_source_warnings_read_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            _, secret = create_project(project)
            secret.write_text("CANARY = 'changed-private-canary'\n", encoding="utf-8")
            expected = load_stored_index(project)
            snapshot = snapshot_sources(project, load_config(project))
            warning = SourceWarning(path="linked.py", reason="symbolic link skipped")
            before = file_state(project)

            with mock.patch.object(
                current_index,
                "snapshot_sources",
                return_value=replace(snapshot, warnings=(warning,)),
            ):
                loaded, current_snapshot = load_current_index(project)

            self.assertEqual(loaded, expected)
            self.assertEqual(current_snapshot, replace(snapshot, warnings=(warning,)))
            self.assertEqual(file_state(project), before)

    @unittest.skipIf(os.name == "nt", "Windows holds approval files open")
    def test_approval_rejects_a_policy_change_without_source_changes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            create_project(project)
            (project / "empty_private_zone").mkdir()
            _, snapshot, approval = load_current_index_for_approval(project)
            try:
                revalidate_current_index_approval(project, approval)
                register_boundary(
                    "empty_private_zone",
                    "Private zone",
                    "private-zone",
                    start=project,
                )

                self.assertEqual(
                    snapshot_sources(
                        project,
                        load_config(project),
                        protected_root_descriptor=approval._resources.root_fd,
                    ).digest,
                    snapshot.digest,
                )
                with self.assertRaisesRegex(CurrentIndexError, "settings changed during approval"):
                    revalidate_current_index_approval(project, approval)
            finally:
                approval.close()

    @unittest.skipUnless(os.name == "nt", "Windows approval handle test")
    def test_approval_holds_policy_files_until_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            create_project(project)
            (project / "empty_private_zone").mkdir()
            state = project / ".silobrief"
            config_path = state / "config.json"
            index_path = state / "index.json"

            def stored_state(path: Path) -> tuple[bytes, int, int, int, int]:
                metadata = path.stat()
                return (
                    path.read_bytes(),
                    metadata.st_dev,
                    metadata.st_ino,
                    metadata.st_size,
                    metadata.st_mtime_ns,
                )

            config_before = stored_state(config_path)
            index_before = stored_state(index_path)
            _, _, approval = load_current_index_for_approval(project)
            try:
                with self.assertRaises(OSError):
                    config_path.rename(state / "config-moved.json")
                revalidate_current_index_approval(project, approval)
                with self.assertRaises(SetupError):
                    register_boundary(
                        "empty_private_zone",
                        "Private zone",
                        "private-zone",
                        start=project,
                    )
                self.assertEqual(stored_state(config_path), config_before)
                self.assertEqual(stored_state(index_path), index_before)
                self.assertEqual(list(state.glob(".*.tmp")), [])
            finally:
                approval.close()

            result = register_boundary(
                "empty_private_zone",
                "Private zone",
                "private-zone",
                start=project,
            )
            self.assertTrue(result.changed)
            self.assertNotEqual(config_path.read_bytes(), config_before[0])
            self.assertTrue(load_stored_index(project).stale)

    @unittest.skipUnless(sys.platform == "linux", "inotify requires Linux")
    def test_approval_watch_remembers_rapid_root_and_state_replacements(self) -> None:
        original_generation = current_index._file_generation
        for target_name in ("root", "state"):
            with self.subTest(target=target_name), tempfile.TemporaryDirectory() as directory:
                base = Path(directory)
                project = base / "project"
                project.mkdir()
                create_project(project)
                target = project if target_name == "root" else project / STATE_DIRECTORY
                backup = base / f"{target.name}-backup"
                replacement = base / f"{target.name}-replacement"
                replacement.mkdir()

                def coarse_generation(
                    metadata: os.stat_result,
                ) -> current_index._FileGeneration:
                    return replace(
                        original_generation(metadata),
                        modified_time_ns=0,
                        changed_time_ns=0,
                    )

                with mock.patch.object(
                    current_index,
                    "_file_generation",
                    side_effect=coarse_generation,
                ):
                    _, _, approval = load_current_index_for_approval(project)
                    try:
                        target.rename(backup)
                        replacement.rename(target)
                        target.rename(replacement)
                        backup.rename(target)
                        for _ in range(2):
                            with self.assertRaisesRegex(
                                CurrentIndexError,
                                "settings changed during approval",
                            ):
                                revalidate_current_index_approval(project, approval)
                    finally:
                        approval.close()

    @unittest.skipUnless(sys.platform == "linux", "inotify requires Linux")
    def test_approval_watch_covers_state_binding(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "project"
            project.mkdir()
            create_project(project)
            state = project / STATE_DIRECTORY
            backup = project / f"{STATE_DIRECTORY}-backup"
            replacement = project / f"{STATE_DIRECTORY}-replacement"
            replacement.mkdir()
            original_open = current_index._open_entry

            def open_then_replace(
                path: Path,
                name: str,
                parent_descriptor: int | None,
                is_directory: bool,
            ) -> tuple[int, current_index._FileGeneration]:
                opened = original_open(path, name, parent_descriptor, is_directory)
                if name == STATE_DIRECTORY:
                    state.rename(backup)
                    replacement.rename(state)
                    state.rename(replacement)
                    backup.rename(state)
                return opened

            with (
                mock.patch.object(
                    current_index,
                    "_open_entry",
                    side_effect=open_then_replace,
                ),
                self.assertRaisesRegex(CurrentIndexError, "settings changed during approval"),
            ):
                load_current_index_for_approval(project)

    def test_v1_0_4_index_requires_init_before_it_can_be_used(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            source = project / "service.py"
            source.write_text("def run():\n    return 1\n", encoding="utf-8", newline="\n")
            setup_project(project)
            state = project / ".silobrief"
            index_path = state / "index.json"
            index_path.write_bytes(V1_0_4_INDEX.read_bytes())
            legacy_bytes = index_path.read_bytes()
            config_bytes = (state / "config.json").read_bytes()
            notes_bytes = (state / "notes.json").read_bytes()
            source_bytes = source.read_bytes()
            before_setup = file_state(project)
            legacy_index = object_file(index_path)

            self.assertEqual(legacy_index["index_version"], 1)
            self.assertEqual(legacy_index["config_digest"], config_digest(load_config(project)))
            self.assertEqual(
                legacy_index["source_digest"],
                snapshot_sources(project, load_config(project)).digest,
            )

            self.assertFalse(setup_project(project))
            self.assertEqual(file_state(project), before_setup)

            with self.assertRaises(StoredIndexError) as caught:
                load_current_index(project)

            self.assertIn("outdated", str(caught.exception))
            self.assertIn("run sb init", str(caught.exception))
            self.assertEqual(index_path.read_bytes(), legacy_bytes)

            initialize_index(project)
            rebuilt_index = object_file(index_path)
            self.assertEqual(rebuilt_index["index_version"], 3)
            self.assertEqual(rebuilt_index["config_digest"], legacy_index["config_digest"])
            self.assertEqual(rebuilt_index["source_digest"], legacy_index["source_digest"])
            loaded, snapshot = load_current_index(project)

            self.assertEqual(loaded.index_version, 3)
            self.assertEqual(loaded.source_digest, snapshot.digest)
            self.assertEqual((state / "config.json").read_bytes(), config_bytes)
            self.assertEqual((state / "notes.json").read_bytes(), notes_bytes)
            self.assertEqual(source.read_bytes(), source_bytes)
            current_state = file_state(project)
            self.assertFalse(setup_project(project))
            self.assertEqual(file_state(project), current_state)

    def test_stale_and_config_mismatch_stop_before_source_collection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            create_project(project)
            index_path = project / ".silobrief" / "index.json"
            index = object_file(index_path)
            index["stale"] = True
            write_object(index_path, index)

            with (
                mock.patch.object(current_index, "load_source_config") as load_current_config,
                mock.patch.object(current_index, "snapshot_sources") as collect_sources,
            ):
                self.assert_current_error(project, "stale")

            load_current_config.assert_not_called()
            collect_sources.assert_not_called()

        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            create_project(project)
            config_path = project / ".silobrief" / "config.json"
            config = object_file(config_path)
            boundaries = config["boundaries"]
            if not isinstance(boundaries, list) or not isinstance(boundaries[0], dict):
                raise AssertionError("fixture config must contain a boundary")
            cast(dict[str, object], boundaries[0])["description"] = "Changed description"
            write_object(config_path, config)

            with mock.patch.object(current_index, "snapshot_sources") as collect_sources:
                self.assert_current_error(project, "configuration changed")

            collect_sources.assert_not_called()

    def test_rejects_added_removed_and_modified_allowed_sources(self) -> None:
        for change in ("added", "removed", "modified"):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as directory:
                project = Path(directory)
                source, _ = create_project(project)
                if change == "added":
                    (project / "added.py").write_text("VALUE = 1\n", encoding="utf-8")
                elif change == "removed":
                    source.unlink()
                else:
                    source.write_text("def run():\n    return 2\n", encoding="utf-8")

                self.assert_current_error(project, "sources changed")

    def test_preserves_existing_loader_error_boundaries(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            create_project(project)
            (project / ".silobrief" / "index.json").unlink()

            with self.assertRaises(StoredIndexError):
                load_current_index(project)

        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            create_project(project)
            (project / ".silobrief" / "config.json").write_text("{}\n", encoding="utf-8")

            with self.assertRaises(SetupError):
                load_current_index(project)

        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            create_project(project)

            with (
                mock.patch.object(
                    current_index,
                    "snapshot_sources",
                    side_effect=SourceCollectionError("cannot collect sources"),
                ),
                self.assertRaises(SourceCollectionError),
            ):
                load_current_index(project)
