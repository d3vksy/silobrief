from __future__ import annotations

import ast
import io
import re
import tokenize
from dataclasses import dataclass

from silobrief.python_structure import Definition, PythonParseError
from silobrief.sources import SourceFile

_WORD_PATTERN = re.compile(r"[^\W_]+", re.UNICODE)
_IDENTIFIER_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")
_CODING_COOKIE = re.compile(r"coding[:=][ \t]*[-\w.]+", re.ASCII)


@dataclass(frozen=True, slots=True)
class SourceTextTokens:
    comments: tuple[str, ...]
    docstrings: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ScopedSourceTextTokens:
    module: SourceTextTokens
    definitions: tuple[tuple[str, SourceTextTokens], ...]


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


def extract_scoped_source_text_tokens(
    source: SourceFile,
    definitions: tuple[Definition, ...],
) -> ScopedSourceTextTokens:
    tree = _parse_source(source)
    docstrings = _scoped_docstrings(tree)
    comments = _scoped_comments(source, definitions)
    names = tuple(sorted({definition.qualified_name for definition in definitions}))
    return ScopedSourceTextTokens(
        module=_scope_tokens(None, comments, docstrings),
        definitions=tuple((name, _scope_tokens(name, comments, docstrings)) for name in names),
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
    return [value for _, value in _comment_entries(source)]


def _comment_entries(source: SourceFile) -> list[tuple[int, str]]:
    result: list[tuple[int, str]] = []
    try:
        tokens = tokenize.tokenize(io.BytesIO(source.content).readline)
        for token in tokens:
            if token.type != tokenize.COMMENT or _is_metadata_comment(token):
                continue
            result.append((token.start[0], token.string.removeprefix("#")))
    except tokenize.TokenError as error:
        line, column = _token_error_location(error)
        reason = str(error.args[0]) if error.args else "tokenization failed"
        raise PythonParseError(source.path, line, column, reason) from error
    return result


def _scoped_comments(
    source: SourceFile,
    definitions: tuple[Definition, ...],
) -> dict[str | None, list[str]]:
    result: dict[str | None, list[str]] = {}
    for line, value in _comment_entries(source):
        owner = _comment_owner(line, definitions)
        result.setdefault(owner, []).append(value)
    return result


def _comment_owner(line: int, definitions: tuple[Definition, ...]) -> str | None:
    containing = tuple(
        definition
        for definition in definitions
        if definition.start_line <= line <= definition.end_line
    )
    if not containing:
        return None
    owner = max(
        containing,
        key=lambda definition: (
            definition.qualified_name.count("."),
            definition.start_line,
            -definition.end_line,
        ),
    )
    return owner.qualified_name


def _scoped_docstrings(tree: ast.Module) -> dict[str | None, list[str]]:
    visitor = _DocstringVisitor()
    visitor.visit(tree)
    return visitor.values


def _scope_tokens(
    scope: str | None,
    comments: dict[str | None, list[str]],
    docstrings: dict[str | None, list[str]],
) -> SourceTextTokens:
    return SourceTextTokens(
        comments=normalize_search_tokens(*comments.get(scope, ())),
        docstrings=normalize_search_tokens(*docstrings.get(scope, ())),
    )


class _DocstringVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.values: dict[str | None, list[str]] = {}
        self._contexts: list[str] = []

    def visit_Module(self, node: ast.Module) -> None:
        self._record(None, node)
        self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._visit_definition(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_definition(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_definition(node)

    def _visit_definition(
        self,
        node: ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef,
    ) -> None:
        parent = self._contexts[-1] if self._contexts else None
        qualified_name = f"{parent}.{node.name}" if parent else node.name
        self._record(qualified_name, node)
        self._contexts.append(qualified_name)
        try:
            self.generic_visit(node)
        finally:
            self._contexts.pop()

    def _record(
        self,
        scope: str | None,
        node: ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef,
    ) -> None:
        value = ast.get_docstring(node, clean=False)
        if value is not None:
            self.values.setdefault(scope, []).append(value)


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
