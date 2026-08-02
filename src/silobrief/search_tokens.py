from __future__ import annotations

import ast
import io
import re
import tokenize
from dataclasses import dataclass

from silobrief.python_structure import PythonParseError
from silobrief.sources import SourceFile

_WORD_PATTERN = re.compile(r"[^\W_]+", re.UNICODE)
_IDENTIFIER_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")
_CODING_COOKIE = re.compile(r"coding[:=][ \t]*[-\w.]+", re.ASCII)


@dataclass(frozen=True, slots=True)
class SourceTextTokens:
    comments: tuple[str, ...]
    docstrings: tuple[str, ...]


def normalize_search_tokens(*values: str) -> tuple[str, ...]:
    normalized: set[str] = set()
    for value in values:
        for word in _WORD_PATTERN.findall(value):
            for part in _IDENTIFIER_BOUNDARY.split(word):
                token = part.casefold()
                if token:
                    normalized.add(token)
    return tuple(sorted(normalized))


def extract_source_text_tokens(source: SourceFile) -> SourceTextTokens:
    tree = _parse_source(source)
    docstrings = tuple(_docstrings(tree))
    comments = tuple(_comments(source))
    return SourceTextTokens(
        comments=normalize_search_tokens(*comments),
        docstrings=normalize_search_tokens(*docstrings),
    )


def _parse_source(source: SourceFile) -> ast.Module:
    try:
        return ast.parse(source.content, filename=source.path, mode="exec")
    except SyntaxError as error:
        raise PythonParseError(
            path=source.path,
            line=error.lineno,
            column=error.offset,
            reason=error.msg,
        ) from error


def _docstrings(tree: ast.Module) -> list[str]:
    result: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            value = ast.get_docstring(node, clean=False)
            if value is not None:
                result.append(value)
    return result


def _comments(source: SourceFile) -> list[str]:
    result: list[str] = []
    try:
        tokens = tokenize.tokenize(io.BytesIO(source.content).readline)
        for token in tokens:
            if token.type != tokenize.COMMENT or _is_metadata_comment(token):
                continue
            result.append(token.string.removeprefix("#"))
    except tokenize.TokenError as error:
        line, column = _token_error_location(error)
        reason = str(error.args[0]) if error.args else "tokenization failed"
        raise PythonParseError(source.path, line, column, reason) from error
    return result


def _is_metadata_comment(token: tokenize.TokenInfo) -> bool:
    if token.start[0] == 1 and token.string.startswith("#!"):
        return True
    return token.start[0] <= 2 and _CODING_COOKIE.search(token.string) is not None


def _token_error_location(error: tokenize.TokenError) -> tuple[int | None, int | None]:
    if len(error.args) < 2:
        return None, None
    location = error.args[1]
    if not isinstance(location, tuple) or len(location) != 2:
        return None, None
    line, column = location
    if not isinstance(line, int) or not isinstance(column, int):
        return None, None
    return line, column + 1
