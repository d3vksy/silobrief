from __future__ import annotations

import io
import tokenize
from collections.abc import Iterable
from dataclasses import dataclass

from silobrief.index import NodeKind
from silobrief.python_structure import (
    Definition,
    DefinitionKind,
    PythonParseError,
    extract_module_structure,
)
from silobrief.sources import SourceFile, SourceSnapshot

MAX_SOURCE_LINES = 4_000
MAX_SOURCE_UTF8_BYTES = 256 * 1024


class SourceExcerptError(Exception):
    pass


class SourceExcerptLimitError(SourceExcerptError):
    lines: int
    utf8_bytes: int

    def __init__(self, lines: int, utf8_bytes: int) -> None:
        self.lines = lines
        self.utf8_bytes = utf8_bytes
        super().__init__(
            f"source excerpts exceed the disclosure limit: {lines} lines, {utf8_bytes} UTF-8 bytes"
        )


@dataclass(frozen=True, slots=True)
class SourceSelection:
    path: str
    kind: NodeKind
    qualified_name: str


@dataclass(frozen=True, slots=True)
class SourceExcerpt:
    path: str
    kind: DefinitionKind
    qualified_name: str
    start_line: int
    end_line: int
    content: str

    @property
    def line_count(self) -> int:
        return self.end_line - self.start_line + 1

    @property
    def utf8_bytes(self) -> int:
        return len(self.content.encode("utf-8"))


def extract_source_excerpts(
    snapshot: SourceSnapshot,
    selections: Iterable[SourceSelection],
    *,
    max_lines: int = MAX_SOURCE_LINES,
    max_utf8_bytes: int = MAX_SOURCE_UTF8_BYTES,
) -> tuple[SourceExcerpt, ...]:
    if max_lines < 0 or max_utf8_bytes < 0:
        raise ValueError("source excerpt limits cannot be negative")

    sources = {source.path: source for source in snapshot.files}
    definitions: dict[str, dict[tuple[DefinitionKind, str], Definition]] = {}
    decoded: dict[str, str] = {}
    excerpts: list[SourceExcerpt] = []

    for selection in sorted(set(selections), key=_selection_key):
        if selection.kind == "module":
            raise SourceExcerptError("module source excerpts are not supported")
        source = sources.get(selection.path)
        if source is None:
            raise SourceExcerptError(
                f"source file is not in the current snapshot: {selection.path}"
            )

        if selection.path not in definitions:
            definitions[selection.path] = _definition_map(source)
            decoded[selection.path] = _decode_source(source)
        definition = definitions[selection.path].get((selection.kind, selection.qualified_name))
        if definition is None:
            raise SourceExcerptError(
                "source definition is not in the current snapshot: "
                f"{selection.path} {selection.qualified_name}"
            )
        excerpts.append(_excerpt(selection, definition, decoded[selection.path]))

    result = _remove_enclosed_excerpts(excerpts)
    lines = sum(item.line_count for item in result)
    utf8_bytes = sum(item.utf8_bytes for item in result)
    if lines > max_lines or utf8_bytes > max_utf8_bytes:
        raise SourceExcerptLimitError(lines, utf8_bytes)
    return result


def _definition_map(source: SourceFile) -> dict[tuple[DefinitionKind, str], Definition]:
    try:
        structure = extract_module_structure(source)
    except PythonParseError as error:
        raise SourceExcerptError(str(error)) from error
    return {
        (definition.kind, definition.qualified_name): definition
        for definition in structure.definitions
    }


def _decode_source(source: SourceFile) -> str:
    try:
        encoding, _ = tokenize.detect_encoding(io.BytesIO(source.content).readline)
        text = source.content.decode(encoding)
    except (LookupError, SyntaxError, UnicodeDecodeError) as error:
        raise SourceExcerptError(f"cannot decode source file: {source.path}") from error
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _excerpt(
    selection: SourceSelection,
    definition: Definition,
    source: str,
) -> SourceExcerpt:
    return SourceExcerpt(
        path=selection.path,
        kind=definition.kind,
        qualified_name=definition.qualified_name,
        start_line=definition.start_line,
        end_line=definition.end_line,
        content=_source_lines(source, definition.start_line, definition.end_line),
    )


def _source_lines(source: str, start_line: int, end_line: int) -> str:
    lines = source.split("\n")
    content = "\n".join(lines[start_line - 1 : end_line])
    if end_line < len(lines):
        content += "\n"
    return content


def _remove_enclosed_excerpts(excerpts: list[SourceExcerpt]) -> tuple[SourceExcerpt, ...]:
    ordered = sorted(excerpts, key=_excerpt_span_key)
    result: list[SourceExcerpt] = []
    for candidate in ordered:
        if any(_contains(existing, candidate) for existing in result):
            continue
        result.append(candidate)
    return tuple(sorted(result, key=_excerpt_output_key))


def _contains(outer: SourceExcerpt, inner: SourceExcerpt) -> bool:
    return (
        outer.path == inner.path
        and outer.start_line <= inner.start_line
        and outer.end_line >= inner.end_line
    )


def _selection_key(selection: SourceSelection) -> tuple[str, str, str]:
    return selection.path, selection.kind, selection.qualified_name


def _excerpt_span_key(excerpt: SourceExcerpt) -> tuple[str, int, int, str]:
    return excerpt.path, excerpt.start_line, -excerpt.end_line, excerpt.qualified_name


def _excerpt_output_key(excerpt: SourceExcerpt) -> tuple[str, int, int, str]:
    return excerpt.path, excerpt.start_line, excerpt.end_line, excerpt.qualified_name
