from __future__ import annotations

import hashlib
import unittest

from silobrief.index import build_index, render_index_json
from silobrief.python_structure import extract_structures
from silobrief.sources import SourceFile, SourceSnapshot
from silobrief.state import DEFAULT_EXCLUDES, BoundaryData, ConfigData


def source_snapshot(path: str, content: bytes) -> SourceSnapshot:
    source = SourceFile(
        path=path,
        content=content,
        sha256=hashlib.sha256(content).hexdigest(),
    )
    return SourceSnapshot(files=(source,), warnings=(), digest="a" * 64)


def config(*boundaries: BoundaryData) -> ConfigData:
    return ConfigData(
        boundaries=list(boundaries),
        default_excludes=list(DEFAULT_EXCLUDES),
        schema_version=1,
    )


class BoundaryPlaceholderTests(unittest.TestCase):
    def test_replaces_directory_boundary_imports_calls_and_references(self) -> None:
        snapshot = source_snapshot(
            "app.py",
            (
                b"from vault_private.gateway import SecretClient as hidden_client\n"
                b"import vault_private.worker as hidden_worker\n"
                b"import requests as http\n"
                b"def run():\n"
                b"    client = hidden_client\n"
                b"    hidden_client()\n"
                b"    hidden_worker.execute()\n"
                b"    vault_private.worker.status\n"
                b"    http.get()\n"
            ),
        )
        boundary = BoundaryData(
            alias="internal-service",
            description="Approved internal service",
            path="vault_private",
        )

        rendered = render_index_json(
            build_index(snapshot, extract_structures(snapshot), config(boundary))
        )

        placeholder = (
            b'{\n        "alias": "internal-service",\n'
            b'        "description": "Approved internal service",\n'
            b'        "kind": "boundary-placeholder"\n      }'
        )
        self.assertIn(placeholder, rendered)
        self.assertIn(b'"target": "requests"', rendered)
        self.assertIn(b'"target": "http.get"', rendered)
        self.assertIn(
            b'"imports": [\n          "approved",\n          "http",\n'
            b'          "internal",\n          "requests",\n          "service"\n        ]',
            rendered,
        )
        for forbidden in (
            b"vault_private",
            b"gateway",
            b"SecretClient",
            b"secret",
            b"client",
            b"hidden_client",
            b"hidden_worker",
            b"worker",
            b"status",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, rendered)

    def test_resolves_relative_file_boundary_deterministically(self) -> None:
        snapshot = source_snapshot(
            "package/public.py",
            (
                b"from .private_zone import HiddenThing as local_hidden\n"
                b"def build():\n"
                b"    return local_hidden\n"
            ),
        )
        private = BoundaryData(
            alias="internal-module",
            description="Approved module",
            path="package/private_zone.py",
        )
        unused = BoundaryData(
            alias="unused-boundary",
            description="Unused boundary",
            path="unused",
        )
        structures = extract_structures(snapshot)

        first = render_index_json(build_index(snapshot, structures, config(private, unused)))
        second = render_index_json(build_index(snapshot, structures, config(unused, private)))

        self.assertEqual(first, second)
        self.assertIn(b'"alias": "internal-module"', first)
        self.assertIn(b'"description": "Approved module"', first)
        for forbidden in (b"private_zone", b"HiddenThing", b"local_hidden"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, first)


if __name__ == "__main__":
    unittest.main()
