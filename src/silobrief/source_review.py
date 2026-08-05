from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import TextIO

from silobrief.boundary_placeholders import BoundaryPlaceholder
from silobrief.index import IndexData
from silobrief.python_structure import DefinitionKind
from silobrief.review import ReviewNode, ReviewSelection
from silobrief.source_excerpts import (
    SourceExcerpt,
    SourceExcerptError,
    SourceExcerptLimitError,
    SourceSelection,
    extract_source_excerpt,
    prepare_source_excerpts,
)
from silobrief.sources import SourceSnapshot


class SourceReviewError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ApprovedSourceExcerpt:
    path: str
    kind: DefinitionKind
    qualified_name: str
    start_line: int
    end_line: int
    content: str
    boundary_aliases: tuple[str, ...]

    @property
    def line_count(self) -> int:
        return self.end_line - self.start_line + 1

    @property
    def utf8_bytes(self) -> int:
        return len(self.content.encode("utf-8"))


def review_source_disclosure(
    index: IndexData,
    snapshot: SourceSnapshot,
    selection: ReviewSelection,
    *,
    input_stream: TextIO,
    output_stream: TextIO,
) -> tuple[ApprovedSourceExcerpt, ...]:
    if not input_stream.isatty() or not output_stream.isatty():
        raise SourceReviewError("source review requires an interactive terminal")

    selected_nodes = {
        (node.path, node.kind, node.qualified_name): node
        for node in selection.selected
        if node.kind != "module"
    }
    candidates: list[SourceExcerpt] = []
    for node in sorted(selected_nodes.values(), key=_node_key):
        try:
            candidates.append(
                extract_source_excerpt(
                    snapshot,
                    SourceSelection(node.path, node.kind, node.qualified_name),
                )
            )
        except SourceExcerptError as error:
            _write(
                output_stream,
                f"Source excerpt unavailable: {node.path} {node.qualified_name}: {error}\n",
            )

    candidates = list(
        prepare_source_excerpts(
            candidates,
            max_lines=sys.maxsize,
            max_utf8_bytes=sys.maxsize,
        )
    )
    if candidates:
        _write(
            output_stream,
            "Source disclosure warning: approved excerpts are copied verbatim and may contain "
            "identifiers, paths, URLs, strings, or secrets that are not classified "
            "automatically.\n",
        )

    aliases = {
        _excerpt_key(excerpt): _boundary_aliases(
            index,
            selected_nodes[_excerpt_key(excerpt)].id,
        )
        for excerpt in candidates
    }
    approved: tuple[SourceExcerpt, ...] = ()
    for candidate in candidates:
        _show_candidate(candidate, aliases[_excerpt_key(candidate)], output_stream)
        answer = _read_line("Include this source excerpt? [y/N]: ", input_stream, output_stream)
        if answer not in {"", "n", "y"}:
            raise SourceReviewError("source answer must be y, n, or blank")
        if answer != "y":
            continue
        try:
            approved = prepare_source_excerpts((*approved, candidate))
        except SourceExcerptLimitError as error:
            _write(output_stream, f"Source excerpt skipped: {error}\n")

    exposed = tuple(
        sorted({alias for excerpt in approved for alias in aliases[_excerpt_key(excerpt)]})
    )
    if exposed:
        _write(
            output_stream, f"Boundary aliases exposed in approved source: {', '.join(exposed)}\n"
        )
        if (
            _read_line(
                "Type exactly EXPOSE to include boundary identifiers: ",
                input_stream,
                output_stream,
            )
            != "EXPOSE"
        ):
            approved = tuple(excerpt for excerpt in approved if not aliases[_excerpt_key(excerpt)])

    return tuple(_approved_excerpt(excerpt, aliases[_excerpt_key(excerpt)]) for excerpt in approved)


def _approved_excerpt(
    excerpt: SourceExcerpt,
    aliases: tuple[str, ...],
) -> ApprovedSourceExcerpt:
    return ApprovedSourceExcerpt(
        path=excerpt.path,
        kind=excerpt.kind,
        qualified_name=excerpt.qualified_name,
        start_line=excerpt.start_line,
        end_line=excerpt.end_line,
        content=excerpt.content,
        boundary_aliases=aliases,
    )


def _boundary_aliases(index: IndexData, node_id: str) -> tuple[str, ...]:
    included = {node_id}
    changed = True
    while changed:
        changed = False
        for edge in index.edges:
            if edge.kind != "contains" or edge.source_id not in included or edge.target_id is None:
                continue
            if edge.target_id not in included:
                included.add(edge.target_id)
                changed = True
    return tuple(
        sorted(
            {
                edge.target.alias
                for edge in index.edges
                if edge.source_id in included and isinstance(edge.target, BoundaryPlaceholder)
            }
        )
    )


def _show_candidate(
    excerpt: SourceExcerpt,
    aliases: tuple[str, ...],
    output: TextIO,
) -> None:
    _write(
        output,
        f"Source candidate: {excerpt.path} | {excerpt.kind} {excerpt.qualified_name} | "
        f"lines {excerpt.start_line}-{excerpt.end_line}\n"
        f"Boundary aliases: {', '.join(aliases) if aliases else 'none'}\n"
        "```python\n",
    )
    _write(output, excerpt.content)
    if not excerpt.content.endswith("\n"):
        _write(output, "\n")
    _write(output, "```\n")


def _read_line(label: str, input_stream: TextIO, output_stream: TextIO) -> str:
    _write(output_stream, label)
    try:
        output_stream.flush()
        return input_stream.readline().rstrip("\r\n")
    except OSError as error:
        raise SourceReviewError("interactive terminal input failed") from error


def _write(output: TextIO, value: str) -> None:
    try:
        output.write(value)
    except OSError as error:
        raise SourceReviewError("interactive terminal output failed") from error


def _node_key(node: ReviewNode) -> tuple[str, str, str, str]:
    return node.path, node.kind, node.qualified_name, node.id


def _excerpt_key(excerpt: SourceExcerpt) -> tuple[str, DefinitionKind, str]:
    return excerpt.path, excerpt.kind, excerpt.qualified_name
