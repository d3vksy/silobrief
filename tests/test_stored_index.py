from __future__ import annotations

import json
import tempfile
import unittest
from collections.abc import Callable
from pathlib import Path
from typing import cast

from silobrief.boundaries import register_boundary
from silobrief.index import render_index_json
from silobrief.initialization import initialize_index
from silobrief.state import setup_project
from silobrief.stored_index import StoredIndexError, load_stored_index


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


def invalidate_version(value: dict[str, object]) -> None:
    value["index_version"] = True


def use_future_version(value: dict[str, object]) -> None:
    value["index_version"] = 3


def invalidate_digest(value: dict[str, object]) -> None:
    value["source_digest"] = "not-a-digest"


def invalidate_node_id(value: dict[str, object]) -> None:
    node = object_value(array_value(value["nodes"])[0])
    node["id"] = "node-invalid"


def invalidate_tokens(value: dict[str, object]) -> None:
    node = object_value(array_value(value["nodes"])[0])
    object_value(node["tokens"])["symbol"] = ["duplicate", "duplicate"]


def invalidate_edge_source(value: dict[str, object]) -> None:
    edge = object_value(array_value(value["edges"])[0])
    edge["source_id"] = "node-missing"


def invalidate_edge_target(value: dict[str, object]) -> None:
    edge = object_value(array_value(value["edges"])[0])
    edge["target_id"] = "node-missing"


def reverse_nodes(value: dict[str, object]) -> None:
    array_value(value["nodes"]).reverse()


def expose_placeholder_name(value: dict[str, object]) -> None:
    for item in array_value(value["edges"]):
        target = object_value(item).get("target")
        if isinstance(target, dict):
            object_value(target)["real_name"] = "private.secret"
            return
    raise AssertionError("fixture index has no boundary placeholder")


class StoredIndexTests(unittest.TestCase):
    def assert_index_error(self, project: Path, expected: str) -> str:
        with self.assertRaises(StoredIndexError) as caught:
            load_stored_index(project)
        message = str(caught.exception)
        self.assertIn(expected, message)
        self.assertNotIn(str(project), message)
        self.assertNotIn("fixture-private-canary", message)
        return message

    def test_loads_a_canonical_index_without_modifying_project_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            create_index(project)
            before = file_state(project)

            loaded = load_stored_index(project)

            self.assertEqual(
                render_index_json(loaded),
                (project / ".silobrief" / "index.json").read_bytes(),
            )
            self.assertEqual(file_state(project), before)

    def test_rejects_schema_and_canonical_encoding_changes(self) -> None:
        mutations: tuple[tuple[str, Callable[[dict[str, object]], None]], ...] = (
            ("unknown key", add_unknown_key),
            ("version", invalidate_version),
            ("future version", use_future_version),
            ("digest", invalidate_digest),
            ("node", invalidate_node_id),
            ("tokens", invalidate_tokens),
            ("edge", invalidate_edge_source),
            ("edge target", invalidate_edge_target),
            ("node order", reverse_nodes),
            ("placeholder", expose_placeholder_name),
        )
        for name, mutate in mutations:
            with self.subTest(case=name), tempfile.TemporaryDirectory() as directory:
                project = Path(directory)
                create_index(project)
                index = project / ".silobrief" / "index.json"
                value = index_object(project)
                mutate(value)
                index.write_bytes(canonical_json(value))
                before = file_state(project)

                self.assert_index_error(project, "index")

                self.assertEqual(file_state(project), before)

        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            create_index(project)
            index = project / ".silobrief" / "index.json"
            original = index.read_bytes()
            reordered = dict(reversed(tuple(index_object(project).items())))
            variants = (
                ("CRLF", original.replace(b"\n", b"\r\n")),
                ("last newline", original.removesuffix(b"\n")),
                ("key order", (json.dumps(reordered, indent=2) + "\n").encode()),
            )
            for name, content in variants:
                with self.subTest(case=name):
                    index.write_bytes(content)
                    before = file_state(project)

                    self.assert_index_error(project, "canonical")

                    self.assertEqual(file_state(project), before)
