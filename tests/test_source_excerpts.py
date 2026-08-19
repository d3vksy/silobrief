from __future__ import annotations

import hashlib
import unittest

from silobrief.source_excerpts import (
    SourceExcerptError,
    SourceExcerptLimitError,
    SourceSelection,
    extract_source_excerpt,
    extract_source_excerpts,
)
from silobrief.sources import SourceFile, SourceSnapshot


def source_file(path: str, content: bytes) -> SourceFile:
    return SourceFile(
        path=path,
        content=content,
        sha256=hashlib.sha256(content).hexdigest(),
    )


def snapshot(*files: SourceFile) -> SourceSnapshot:
    return SourceSnapshot(files=files, warnings=(), digest="test-snapshot")


class SourceExcerptTests(unittest.TestCase):
    def test_extracts_decorated_sync_async_and_nested_functions(self) -> None:
        source = source_file(
            "service.py",
            (
                b'@route("retry")\r\n'
                b"def retry_request():\r\n"
                b'    """PUBLIC_DOCSTRING."""\r\n'
                b"    # PUBLIC_COMMENT\r\n"
                b'    value = "PUBLIC_STRING"\r\n'
                b"    def nested():\r\n"
                b"        return value\r\n"
                b"    return nested()\r\n"
                b"\r\n"
                b"async def fetch():\r\n"
                b"    return None\r\n"
            ),
        )

        excerpts = extract_source_excerpts(
            snapshot(source),
            (
                SourceSelection("service.py", "function", "retry_request.nested"),
                SourceSelection("service.py", "function", "fetch"),
            ),
        )

        self.assertEqual(
            [(item.qualified_name, item.start_line, item.end_line) for item in excerpts],
            [("retry_request.nested", 6, 7), ("fetch", 10, 11)],
        )
        self.assertEqual(
            excerpts[0].content,
            "    def nested():\n        return value\n",
        )
        self.assertEqual(excerpts[1].content, "async def fetch():\n    return None\n")

    def test_preserves_approved_comments_docstrings_and_strings(self) -> None:
        source = source_file(
            "service.py",
            (
                b'@route("retry")\n'
                b"def retry_request():\n"
                b'    """PUBLIC_DOCSTRING."""\n'
                b"    # PUBLIC_COMMENT\n"
                b'    return "PUBLIC_STRING"\n'
            ),
        )

        (excerpt,) = extract_source_excerpts(
            snapshot(source),
            (SourceSelection("service.py", "function", "retry_request"),),
        )

        self.assertEqual(excerpt.start_line, 1)
        self.assertEqual(excerpt.end_line, 5)
        self.assertEqual(excerpt.line_count, 5)
        self.assertIn('@route("retry")', excerpt.content)
        self.assertIn("PUBLIC_DOCSTRING", excerpt.content)
        self.assertIn("PUBLIC_COMMENT", excerpt.content)
        self.assertIn("PUBLIC_STRING", excerpt.content)

    def test_outer_class_replaces_overlapping_method(self) -> None:
        source = source_file(
            "models.py",
            (
                b"class Service:\n"
                b"    def run(self):\n"
                b"        return 1\n"
                b"\n"
                b"def other():\n"
                b"    return 2\n"
            ),
        )

        excerpts = extract_source_excerpts(
            snapshot(source),
            (
                SourceSelection("models.py", "function", "Service.run"),
                SourceSelection("models.py", "class", "Service"),
                SourceSelection("models.py", "class", "Service"),
                SourceSelection("models.py", "function", "other"),
            ),
        )

        self.assertEqual(
            [item.qualified_name for item in excerpts],
            ["Service", "other"],
        )
        self.assertEqual(
            excerpts[0].content, "class Service:\n    def run(self):\n        return 1\n"
        )

    def test_preserves_every_repeated_definition_span(self) -> None:
        source = source_file(
            "models.py",
            (
                b"class Item:\n"
                b"    @property\n"
                b"    def value(self):\n"
                b"        return self._value\n"
                b"\n"
                b"    @value.setter\n"
                b"    def value(self, new):\n"
                b"        self._value = new\n"
                b"\n"
                b"@overload\n"
                b"def render(value: int) -> str: ...\n"
                b"@overload\n"
                b"def render(value: str) -> str: ...\n"
                b"def render(value):\n"
                b"    return str(value)\n"
                b"\n"
                b"if FLAG:\n"
                b"    def choose():\n"
                b"        return 'first'\n"
                b"else:\n"
                b"    def choose():\n"
                b"        return 'second'\n"
            ),
        )

        excerpts = extract_source_excerpts(
            snapshot(source),
            (
                SourceSelection("models.py", "function", "Item.value"),
                SourceSelection("models.py", "function", "render"),
                SourceSelection("models.py", "function", "choose"),
            ),
        )

        self.assertEqual(
            [item.qualified_name for item in excerpts],
            ["Item.value", "Item.value", "render", "render", "render", "choose", "choose"],
        )
        contents = [item.content for item in excerpts]
        self.assertTrue(any("@property" in content for content in contents))
        self.assertTrue(any("@value.setter" in content for content in contents))
        self.assertEqual(sum("@overload" in content for content in contents), 2)
        self.assertTrue(any("return 'first'" in content for content in contents))
        self.assertTrue(any("return 'second'" in content for content in contents))

    def test_repeated_definitions_share_limits_and_reject_singular_lookup(self) -> None:
        source = source_file(
            "models.py",
            (
                b"class Item:\n"
                b"    @property\n"
                b"    def value(self):\n"
                b"        return self._value\n"
                b"\n"
                b"    @value.setter\n"
                b"    def value(self, new):\n"
                b"        self._value = new\n"
            ),
        )
        selection = SourceSelection("models.py", "function", "Item.value")

        with self.assertRaisesRegex(SourceExcerptLimitError, "6 lines"):
            extract_source_excerpts(snapshot(source), (selection,), max_lines=5)
        with self.assertRaisesRegex(SourceExcerptError, "multiple definitions"):
            extract_source_excerpt(snapshot(source), selection)

    def test_sorts_excerpts_by_path_and_source_location(self) -> None:
        first = source_file("a.py", b"def zed():\n    pass\n\ndef alpha():\n    pass\n")
        second = source_file("b.py", b"def beta():\n    pass\n")

        excerpts = extract_source_excerpts(
            snapshot(second, first),
            (
                SourceSelection("b.py", "function", "beta"),
                SourceSelection("a.py", "function", "alpha"),
                SourceSelection("a.py", "function", "zed"),
            ),
        )

        self.assertEqual(
            [(item.path, item.qualified_name) for item in excerpts],
            [("a.py", "zed"), ("a.py", "alpha"), ("b.py", "beta")],
        )

    def test_decodes_source_encoding_and_emits_utf8_text(self) -> None:
        source = source_file(
            "legacy.py",
            b'# -*- coding: latin-1 -*-\r\ndef label():\r\n    return "caf\xe9"\r\n',
        )

        (excerpt,) = extract_source_excerpts(
            snapshot(source),
            (SourceSelection("legacy.py", "function", "label"),),
        )

        self.assertEqual(excerpt.content, 'def label():\n    return "caf\u00e9"\n')
        self.assertEqual(excerpt.utf8_bytes, len(excerpt.content.encode("utf-8")))

    def test_does_not_parse_unselected_invalid_file(self) -> None:
        selected = source_file("good.py", b"def run():\n    return 1\n")
        unselected = source_file("bad.py", b"def broken(:  # PARSE_CANARY\n")

        (excerpt,) = extract_source_excerpts(
            snapshot(unselected, selected),
            (SourceSelection("good.py", "function", "run"),),
        )

        self.assertEqual(excerpt.path, "good.py")

        with self.assertRaises(SourceExcerptError) as caught:
            extract_source_excerpts(
                snapshot(unselected, selected),
                (SourceSelection("bad.py", "function", "broken"),),
            )
        self.assertNotIn("PARSE_CANARY", str(caught.exception))

    def test_rejects_unsupported_or_missing_selections(self) -> None:
        source = source_file("service.py", b"def run():\n    return 1\n")
        cases = (
            SourceSelection("service.py", "module", "service"),
            SourceSelection("missing.py", "function", "run"),
            SourceSelection("service.py", "function", "missing"),
        )

        for selection in cases:
            with self.subTest(selection=selection):
                with self.assertRaises(SourceExcerptError):
                    extract_source_excerpts(snapshot(source), (selection,))

    def test_rejects_line_and_byte_limit_without_truncating(self) -> None:
        source = source_file("service.py", b"def run():\n    return 'payload'\n")
        selection = SourceSelection("service.py", "function", "run")

        with self.assertRaises(SourceExcerptLimitError) as line_error:
            extract_source_excerpts(snapshot(source), (selection,), max_lines=1)
        self.assertEqual(line_error.exception.lines, 2)

        full = extract_source_excerpts(snapshot(source), (selection,))[0]
        with self.assertRaises(SourceExcerptLimitError) as byte_error:
            extract_source_excerpts(
                snapshot(source),
                (selection,),
                max_utf8_bytes=full.utf8_bytes - 1,
            )
        self.assertEqual(byte_error.exception.utf8_bytes, full.utf8_bytes)


if __name__ == "__main__":
    unittest.main()
