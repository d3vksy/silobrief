from __future__ import annotations

import hashlib
import json
import unittest
from dataclasses import replace

from silobrief.index import (
    IndexBuildError,
    IndexEdge,
    build_index,
    render_index_json,
    stable_node_id,
)
from silobrief.python_structure import extract_structures
from silobrief.sources import SourceFile, SourceSnapshot
from silobrief.state import DEFAULT_EXCLUDES, BoundaryData, ConfigData


def source_file(path: str, content: bytes) -> SourceFile:
    return SourceFile(
        path=path,
        content=content,
        sha256=hashlib.sha256(content).hexdigest(),
    )


def source_snapshot(*files: SourceFile) -> SourceSnapshot:
    digest = hashlib.sha256()
    for source in sorted(files, key=lambda item: item.path):
        digest.update(source.path.encode())
        digest.update(bytes.fromhex(source.sha256))
    return SourceSnapshot(files=files, warnings=(), digest=digest.hexdigest())


def config(*boundaries: BoundaryData) -> ConfigData:
    return ConfigData(
        boundaries=list(boundaries),
        default_excludes=list(DEFAULT_EXCLUDES),
        schema_version=1,
    )


class DeterministicIndexTests(unittest.TestCase):
    def test_stable_node_id_uses_path_kind_and_qualified_name(self) -> None:
        node_id = stable_node_id("package/service.py", "function", "Worker.run")

        self.assertEqual(
            node_id,
            "node-e7c8eeef16b7a03f28e3b09b380ad1bc79aea32e37840daac175804d3d8d0356",
        )
        self.assertEqual(node_id, stable_node_id("package/service.py", "function", "Worker.run"))
        self.assertNotEqual(node_id, stable_node_id("other/service.py", "function", "Worker.run"))
        self.assertNotEqual(node_id, stable_node_id("package/service.py", "class", "Worker.run"))
        self.assertNotEqual(
            node_id, stable_node_id("package/service.py", "function", "Worker.stop")
        )

    def test_builds_nodes_tokens_and_structure_edges(self) -> None:
        source = source_file(
            "package/service.py",
            (
                b'"""Service module."""\n'
                b"import requests as http\n"
                b"def helper():\n"
                b"    pass\n"
                b"class Worker:\n"
                b'    """Worker docs."""\n'
                b"    def execute(self):\n"
                b"        helper()\n"
                b"        self.finish()\n"
                b"        external.call()\n"
                b"    def finish(self):\n"
                b"        pass\n"
                b'SECRET = "INDEX_STRING_CANARY"\n'
            ),
        )
        snapshot = source_snapshot(source)
        structures = extract_structures(snapshot)

        index = build_index(snapshot, structures, config())
        nodes = {node.qualified_name: node for node in index.nodes}

        self.assertEqual(
            set(nodes), {"package.service", "helper", "Worker", "Worker.execute", "Worker.finish"}
        )
        execute = nodes["Worker.execute"]
        self.assertEqual(execute.tokens.path, ("package", "service"))
        self.assertEqual(execute.tokens.symbol, ("execute", "worker"))
        self.assertEqual(execute.tokens.imports, ("http", "requests"))
        self.assertEqual(execute.tokens.comments, ())
        self.assertEqual(execute.tokens.docstrings, ("docs", "module", "service", "worker"))

        module = nodes["package.service"]
        worker = nodes["Worker"]
        helper = nodes["helper"]
        finish = nodes["Worker.finish"]
        self.assertEqual(
            set(index.edges),
            {
                IndexEdge(module.id, "contains", "helper", helper.id),
                IndexEdge(module.id, "contains", "Worker", worker.id),
                IndexEdge(worker.id, "contains", "Worker.execute", execute.id),
                IndexEdge(worker.id, "contains", "Worker.finish", finish.id),
                IndexEdge(module.id, "import", "requests", None),
                IndexEdge(execute.id, "call", "helper", helper.id),
                IndexEdge(execute.id, "call", "self.finish", finish.id),
                IndexEdge(execute.id, "call", "external.call", None),
            },
        )

    def test_json_is_identical_for_equivalent_input_order(self) -> None:
        first_source = source_file(
            "a.py",
            b'"""Alpha docs."""\n# Useful comment\nVALUE = "STRING_LITERAL_CANARY"\n',
        )
        second_source = source_file("package/b.py", b"def BetaValue():\n    pass\n")
        first_snapshot = source_snapshot(first_source, second_source)
        second_snapshot = source_snapshot(second_source, first_source)
        first_structures = extract_structures(first_snapshot)
        second_structures = tuple(reversed(extract_structures(second_snapshot)))
        private = BoundaryData(alias="private", description="Private code", path="private")
        generated = BoundaryData(alias="generated", description="Generated code", path="gen")

        first = build_index(first_snapshot, first_structures, config(private, generated))
        second = build_index(second_snapshot, second_structures, config(generated, private))
        first_json = render_index_json(first)
        second_json = render_index_json(second)

        self.assertEqual(first, second)
        self.assertEqual(first_json, second_json)
        self.assertTrue(first_json.endswith(b"\n"))
        self.assertFalse(first_json.endswith(b"\n\n"))
        self.assertNotIn(b"\r\n", first_json)
        self.assertNotIn(b"STRING_LITERAL_CANARY", first_json)
        parsed = json.loads(first_json)
        self.assertEqual(
            set(parsed),
            {"config_digest", "edges", "index_version", "nodes", "source_digest", "stale"},
        )
        self.assertEqual(parsed["index_version"], 1)
        self.assertIs(parsed["stale"], False)

    def test_config_and_source_digest_changes_are_visible(self) -> None:
        source = source_file("module.py", b"VALUE = 1\n")
        snapshot = source_snapshot(source)
        structures = extract_structures(snapshot)
        original = build_index(
            snapshot,
            structures,
            config(BoundaryData(alias="private", description="Private code", path="private")),
        )
        changed_config = build_index(
            snapshot,
            structures,
            config(BoundaryData(alias="private", description="Internal code", path="private")),
        )
        changed_source = build_index(
            replace(snapshot, digest="f" * 64),
            structures,
            config(BoundaryData(alias="private", description="Private code", path="private")),
        )

        self.assertNotEqual(original.config_digest, changed_config.config_digest)
        self.assertEqual(original.source_digest, changed_config.source_digest)
        self.assertEqual(original.config_digest, changed_source.config_digest)
        self.assertNotEqual(original.source_digest, changed_source.source_digest)

    def test_rejects_mismatched_source_and_structure_paths(self) -> None:
        snapshot = source_snapshot(source_file("module.py", b"VALUE = 1\n"))

        with self.assertRaisesRegex(IndexBuildError, "paths do not match"):
            build_index(snapshot, (), config())


if __name__ == "__main__":
    unittest.main()
