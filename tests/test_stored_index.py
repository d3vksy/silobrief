from __future__ import annotations

import copy
import importlib
import json
import tempfile
import unittest
from collections.abc import Callable
from pathlib import Path
from typing import Protocol, cast
from unittest import mock

from silobrief.boundaries import register_boundary
from silobrief.index import IndexData, render_index_json
from silobrief.initialization import initialize_index
from silobrief.sources import SourceWarning
from silobrief.state import load_config, save_config, setup_project


class LoadedIndexLike(Protocol):
    root: Path
    index: IndexData
    warnings: tuple[SourceWarning, ...]


class StoredIndexModule(Protocol):
    StoredIndexError: type[Exception]

    def load_current_index(self, start: Path) -> LoadedIndexLike: ...


def stored_index_module() -> StoredIndexModule:
    return cast(StoredIndexModule, importlib.import_module("silobrief.stored_index"))


def create_index(project: Path) -> None:
    package = project / "package"
    private = project / "private"
    package.mkdir()
    private.mkdir()
    (package / "service.py").write_text(
        "from private.secret import send\n\n\ndef run():\n    send()\n",
        encoding="utf-8",
        newline="\n",
    )
    (private / "secret.py").write_text(
        "CANARY = 'fixture-private-canary'\n",
        encoding="utf-8",
        newline="\n",
    )
    setup_project(project)
    register_boundary(
        "private",
        "External delivery adapter",
        "delivery-boundary",
        start=project,
    )
    initialize_index(project)


def file_state(project: Path) -> dict[str, tuple[bytes, int]]:
    return {
        path.relative_to(project).as_posix(): (path.read_bytes(), path.stat().st_mtime_ns)
        for path in sorted(project.rglob("*"))
        if path.is_file()
    }


def index_object(project: Path) -> dict[str, object]:
    value: object = json.loads((project / ".silobrief" / "index.json").read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise AssertionError("index must be an object")
    return cast(dict[str, object], value)


def canonical_json(value: dict[str, object]) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()


def object_value(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise AssertionError("expected an object")
    return cast(dict[str, object], value)


def array_value(value: object) -> list[object]:
    if not isinstance(value, list):
        raise AssertionError("expected an array")
    return cast(list[object], value)


def add_unknown_key(value: dict[str, object]) -> None:
    value["unexpected"] = True


def invalidate_node_id(value: dict[str, object]) -> None:
    node = object_value(array_value(value["nodes"])[0])
    node["id"] = "node-invalid"


def invalidate_edge_source(value: dict[str, object]) -> None:
    edge = object_value(array_value(value["edges"])[0])
    edge["source_id"] = "node-missing"


def expose_placeholder_name(value: dict[str, object]) -> None:
    for item in array_value(value["edges"]):
        target = object_value(item).get("target")
        if isinstance(target, dict):
            object_value(target)["real_name"] = "private.secret"
            return
    raise AssertionError("fixture index has no boundary placeholder")


class StoredIndexTests(unittest.TestCase):
    def assert_index_error(self, project: Path, expected: str) -> str:
        module = stored_index_module()
        with self.assertRaises(module.StoredIndexError) as caught:
            module.load_current_index(project)
        message = str(caught.exception)
        self.assertIn(expected, message)
        self.assertNotIn(str(project), message)
        self.assertNotIn("fixture-private-canary", message)
        return message

    def test_loads_a_current_index_from_a_project_subdirectory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            create_index(project)
            before = file_state(project)

            loaded = stored_index_module().load_current_index(project / "package")

            self.assertEqual(loaded.root, project.resolve())
            self.assertEqual(
                render_index_json(loaded.index),
                (project / ".silobrief" / "index.json").read_bytes(),
            )
            self.assertEqual(loaded.warnings, ())
            self.assertEqual(file_state(project), before)

    def test_rejects_schema_and_canonical_encoding_changes(self) -> None:
        mutations: tuple[tuple[str, Callable[[dict[str, object]], None]], ...] = (
            ("unknown key", add_unknown_key),
            ("node", invalidate_node_id),
            ("edge", invalidate_edge_source),
            ("placeholder", expose_placeholder_name),
        )
        for name, mutate in mutations:
            with self.subTest(case=name), tempfile.TemporaryDirectory() as directory:
                project = Path(directory)
                create_index(project)
                index = project / ".silobrief" / "index.json"
                value = copy.deepcopy(index_object(project))
                mutate(value)
                index.write_bytes(canonical_json(value))
                before = file_state(project)

                self.assert_index_error(project, "index")

                self.assertEqual(file_state(project), before)

        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            create_index(project)
            index = project / ".silobrief" / "index.json"
            index.write_bytes(index.read_bytes().replace(b"\n", b"\r\n"))
            before = file_state(project)

            self.assert_index_error(project, "canonical")

            self.assertEqual(file_state(project), before)

    def test_rejects_stale_and_config_mismatch_before_source_collection(self) -> None:
        for case in ("stale", "config"):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as directory:
                project = Path(directory)
                create_index(project)
                if case == "stale":
                    value = index_object(project)
                    value["stale"] = True
                    (project / ".silobrief" / "index.json").write_bytes(canonical_json(value))
                else:
                    config = load_config(project)
                    config["boundaries"][0]["description"] = "Changed public description"
                    save_config(project, config)
                before = file_state(project)

                with mock.patch("silobrief.sources.snapshot_sources") as snapshot:
                    self.assert_index_error(project, case)

                snapshot.assert_not_called()
                self.assertEqual(file_state(project), before)

    def test_rejects_a_changed_source_without_modifying_project_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            create_index(project)
            service = project / "package" / "service.py"
            service.write_text(
                service.read_text(encoding="utf-8") + "\ndef added():\n    return 1\n",
                encoding="utf-8",
                newline="\n",
            )
            before = file_state(project)

            self.assert_index_error(project, "source")

            self.assertEqual(file_state(project), before)
