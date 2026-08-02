from __future__ import annotations

import hashlib
import unittest
from unittest import mock

from silobrief.python_structure import PythonParseError
from silobrief.search_tokens import extract_source_text_tokens, normalize_search_tokens
from silobrief.sources import SourceFile


def source_file(path: str, content: bytes) -> SourceFile:
    return SourceFile(
        path=path,
        content=content,
        sha256=hashlib.sha256(content).hexdigest(),
    )


class SearchTokenTests(unittest.TestCase):
    def test_normalizes_identifiers_punctuation_unicode_and_duplicates(self) -> None:
        tokens = normalize_search_tokens(
            "ParcelClient retry_queue HTTPResponse2XX",
            "배송_상태, Straße; parcel-client",
        )

        self.assertEqual(
            tokens,
            (
                "client",
                "http",
                "parcel",
                "queue",
                "response2",
                "retry",
                "strasse",
                "xx",
                "배송",
                "상태",
            ),
        )
        self.assertEqual(normalize_search_tokens("---", "___"), ())

    def test_extracts_comment_and_real_docstring_tokens_by_source(self) -> None:
        source = source_file(
            "worker.py",
            (
                b'"""Parse ParcelClient responses."""\n'
                b"# Retry HTTPResponse parsing\n"
                b"class Worker:\n"
                b'    """Handles retry_queue."""\n'
                b'    note = "STRING_LITERAL_CANARY"\n'
                b"    async def run(self):\n"
                b'        """Sync external API."""\n'
                b"        # Convert json_payload now\n"
                b'        value = f"FSTRING_CANARY {self}"\n'
                b'        marker = "# STRING_COMMENT_CANARY"\n'
            ),
        )

        tokens = extract_source_text_tokens(source)

        self.assertEqual(
            tokens.comments,
            ("convert", "http", "json", "now", "parsing", "payload", "response", "retry"),
        )
        self.assertEqual(
            tokens.docstrings,
            (
                "api",
                "client",
                "external",
                "handles",
                "parcel",
                "parse",
                "queue",
                "responses",
                "retry",
                "sync",
            ),
        )
        rendered = repr(tokens)
        for canary in ("STRING_LITERAL_CANARY", "FSTRING_CANARY", "STRING_COMMENT_CANARY"):
            with self.subTest(canary=canary):
                self.assertNotIn(canary, rendered)

    def test_ignores_shebang_and_encoding_cookie_comments(self) -> None:
        source = source_file(
            "legacy.py",
            (
                b"#!/usr/bin/env python\n"
                b"# -*- coding: latin-1 -*-\n"
                b'"""Legacy worker."""\n'
                b"# Process caf\xe9_jobs\n"
            ),
        )

        tokens = extract_source_text_tokens(source)

        self.assertEqual(tokens.comments, ("caf\u00e9", "jobs", "process"))
        self.assertEqual(tokens.docstrings, ("legacy", "worker"))
        for metadata_token in ("usr", "bin", "env", "python", "coding", "latin"):
            with self.subTest(token=metadata_token):
                self.assertNotIn(metadata_token, tokens.comments)

    def test_is_deterministic_and_does_not_open_source_files(self) -> None:
        source = source_file(
            "memory_only.py",
            b'"""Repeated repeated Words."""\n# Words more_words\n',
        )

        with (
            mock.patch("builtins.open", side_effect=AssertionError("must not open source")),
            mock.patch("pathlib.Path.open", side_effect=AssertionError("must not open source")),
        ):
            first = extract_source_text_tokens(source)
            second = extract_source_text_tokens(source)

        self.assertEqual(first, second)
        self.assertEqual(first.comments, ("more", "words"))
        self.assertEqual(first.docstrings, ("repeated", "words"))

    def test_reports_syntax_error_without_source_line(self) -> None:
        source = source_file(
            "package/bad.py",
            b"def broken(:  # TOKEN_ERROR_CANARY\n",
        )

        with self.assertRaises(PythonParseError) as caught:
            extract_source_text_tokens(source)

        error = caught.exception
        self.assertEqual(error.path, "package/bad.py")
        self.assertEqual(error.line, 1)
        self.assertEqual(error.column, 12)
        self.assertNotIn("TOKEN_ERROR_CANARY", str(error))


if __name__ == "__main__":
    unittest.main()
