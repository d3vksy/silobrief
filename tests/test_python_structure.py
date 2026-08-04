from __future__ import annotations

import hashlib
import unittest
from unittest import mock

from silobrief.python_structure import (
    Definition,
    ImportEntry,
    PythonParseError,
    SymbolUse,
    extract_structures,
)
from silobrief.sources import SourceFile, SourceSnapshot


def source_file(path: str, content: bytes) -> SourceFile:
    return SourceFile(
        path=path,
        content=content,
        sha256=hashlib.sha256(content).hexdigest(),
    )


def source_snapshot(*files: SourceFile) -> SourceSnapshot:
    return SourceSnapshot(files=files, warnings=(), digest="test-snapshot")


class PythonStructureTests(unittest.TestCase):
    def test_extracts_nested_classes_and_sync_and_async_functions(self) -> None:
        source = source_file(
            "package/service.py",
            (
                b"class Outer:\n"
                b"    class Inner:\n"
                b"        pass\n"
                b"    def method(self):\n"
                b"        pass\n"
                b"    async def fetch(self):\n"
                b"        pass\n"
                b"def top():\n"
                b"    def nested():\n"
                b"        pass\n"
            ),
        )

        (module,) = extract_structures(source_snapshot(source))

        self.assertEqual(module.path, "package/service.py")
        self.assertEqual(
            module.definitions,
            (
                Definition("class", "Outer", "Outer", False, 1, 1, 1, 7),
                Definition("class", "Inner", "Outer.Inner", False, 2, 5, 2, 3),
                Definition("function", "method", "Outer.method", False, 4, 5, 4, 5),
                Definition("function", "fetch", "Outer.fetch", True, 6, 5, 6, 7),
                Definition("function", "top", "top", False, 8, 1, 8, 10),
                Definition("function", "nested", "top.nested", False, 9, 5, 9, 10),
            ),
        )
        self.assertEqual(module.imports, ())
        self.assertEqual(module.calls, ())
        self.assertEqual(module.references, ())

    def test_extracts_import_variants_in_source_order(self) -> None:
        source = source_file(
            "imports.py",
            (
                b"import os, package.client as client\n"
                b"from .service import send as deliver, receive\n"
                b"from .. import shared\n"
                b"from plugins import *\n"
                b"def load():\n"
                b"    import local as scoped\n"
            ),
        )

        (module,) = extract_structures(source_snapshot(source))

        self.assertEqual(
            module.imports,
            (
                ImportEntry("os", None, None, 0, None, 1, 1),
                ImportEntry("package.client", None, "client", 0, None, 1, 1),
                ImportEntry("service", "send", "deliver", 1, None, 2, 1),
                ImportEntry("service", "receive", None, 1, None, 2, 1),
                ImportEntry(None, "shared", None, 2, None, 3, 1),
                ImportEntry("plugins", "*", None, 0, None, 4, 1),
                ImportEntry("local", None, "scoped", 0, "load", 6, 5),
            ),
        )

    def test_extracts_static_calls_and_load_references_without_duplicates(self) -> None:
        source = source_file(
            "calls.py",
            (
                b"def run(payload):\n"
                b"    client.send(payload)\n"
                b"    handler = client.callback\n"
                b"    (get_factory())()\n"
            ),
        )

        (module,) = extract_structures(source_snapshot(source))

        self.assertEqual(
            module.calls,
            (
                SymbolUse("run", "client.send", 2, 5),
                SymbolUse("run", "get_factory", 4, 6),
            ),
        )
        self.assertEqual(
            module.references,
            (
                SymbolUse("run", "payload", 2, 17),
                SymbolUse("run", "client.callback", 3, 15),
            ),
        )

    def test_omits_source_text_comments_docstrings_and_string_literals(self) -> None:
        source = source_file(
            "canaries.py",
            (
                b'"""DOCSTRING_CANARY"""\n'
                b"# COMMENT_CANARY\n"
                b'SECRET = "STRING_CANARY"\n'
                b"def run():\n"
                b'    """METHOD_DOCSTRING_CANARY"""\n'
                b'    return "RETURN_STRING_CANARY"\n'
            ),
        )

        result = extract_structures(source_snapshot(source))
        rendered = repr(result)

        self.assertEqual(
            result[0].definitions,
            (Definition("function", "run", "run", False, 4, 1, 4, 6),),
        )
        for canary in (
            "DOCSTRING_CANARY",
            "COMMENT_CANARY",
            "STRING_CANARY",
            "METHOD_DOCSTRING_CANARY",
            "RETURN_STRING_CANARY",
        ):
            with self.subTest(canary=canary):
                self.assertNotIn(canary, rendered)

    def test_reports_relative_file_and_location_without_source_line(self) -> None:
        good = source_file("a_good.py", b"VALUE = 1\n")
        invalid = source_file("package/bad.py", b"def broken(:  # ERROR_LINE_CANARY\n")

        with self.assertRaises(PythonParseError) as caught:
            extract_structures(source_snapshot(good, invalid))

        error = caught.exception
        self.assertEqual(error.path, "package/bad.py")
        self.assertEqual(error.line, 1)
        self.assertEqual(error.column, 12)
        self.assertIn("invalid syntax", error.reason)
        self.assertNotIn("ERROR_LINE_CANARY", str(error))

    def test_parses_encoding_cookie_from_memory_without_opening_files(self) -> None:
        source = source_file(
            "legacy.py",
            b'# -*- coding: latin-1 -*-\nlabel = "caf\xe9"\n',
        )

        with (
            mock.patch("builtins.open", side_effect=AssertionError("must not open source")),
            mock.patch("pathlib.Path.open", side_effect=AssertionError("must not open source")),
        ):
            result = extract_structures(source_snapshot(source))

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].path, "legacy.py")
        self.assertEqual(result[0].definitions, ())


if __name__ == "__main__":
    unittest.main()
