from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from typing import cast
from unittest import mock

from silobrief import current_index
from silobrief.boundaries import register_boundary
from silobrief.current_index import CurrentIndexError, load_current_index
from silobrief.index import config_digest
from silobrief.initialization import initialize_index
from silobrief.sources import SourceCollectionError, SourceWarning, snapshot_sources
from silobrief.state import SetupError, load_config, setup_project
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
            self.assertEqual(
                index_path.read_bytes(),
                legacy_bytes.replace(b'"index_version": 1', b'"index_version": 2'),
            )
            loaded, snapshot = load_current_index(project)

            self.assertEqual(loaded.index_version, 2)
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
                mock.patch.object(current_index, "load_config") as load_current_config,
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
