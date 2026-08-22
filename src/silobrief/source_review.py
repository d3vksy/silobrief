from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import TextIO

from silobrief.boundary_placeholders import BoundaryPlaceholder
from silobrief.index import IndexData
from silobrief.language import Language, localized
from silobrief.python_structure import DefinitionKind
from silobrief.review import ReviewNode, ReviewSelection
from silobrief.source_excerpts import (
    SourceExcerpt,
    SourceExcerptError,
    SourceExcerptLimitError,
    SourceSelection,
    extract_source_excerpts,
    prepare_source_excerpts,
)
from silobrief.sources import SourceSnapshot
from silobrief.terminal import escape_terminal_line, escape_terminal_preview, write_warning


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
    language: Language = "en",
) -> tuple[ApprovedSourceExcerpt, ...]:
    if not input_stream.isatty() or not output_stream.isatty():
        raise SourceReviewError(
            localized(
                language,
                "source review requires an interactive terminal",
                "소스 검토에는 대화형 터미널이 필요합니다",
            )
        )

    selected_nodes = {
        (node.path, node.kind, node.qualified_name): node
        for node in selection.selected
        if node.kind != "module"
    }
    candidates: list[SourceExcerpt] = []
    for node in sorted(selected_nodes.values(), key=_node_key):
        try:
            candidates.extend(
                extract_source_excerpts(
                    snapshot,
                    (SourceSelection(node.path, node.kind, node.qualified_name),),
                    max_lines=sys.maxsize,
                    max_utf8_bytes=sys.maxsize,
                )
            )
        except SourceExcerptError as error:
            path = escape_terminal_line(node.path)
            qualified_name = escape_terminal_line(node.qualified_name)
            reason = escape_terminal_line(str(error))
            _write(
                output_stream,
                localized(
                    language,
                    f"Source excerpt unavailable: {path} {qualified_name}: {reason}\n",
                    f"소스 발췌를 사용할 수 없음: {path} {qualified_name}: {reason}\n",
                ),
            )

    candidates = list(
        prepare_source_excerpts(
            candidates,
            max_lines=sys.maxsize,
            max_utf8_bytes=sys.maxsize,
        )
    )
    if candidates:
        write_warning(
            output_stream,
            localized(
                language,
                "Approved excerpts are copied verbatim. They may contain identifiers, paths, "
                "URLs, strings, or secrets that siloBrief does not detect automatically.",
                "승인한 발췌는 원문 그대로 복사됩니다. 식별자, 경로, URL, 문자열 또는 "
                "siloBrief가 자동으로 탐지하지 못하는 비밀정보가 포함될 수 있습니다.",
            ),
            label=localized(language, "WARNING", "경고"),
            separate=True,
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
        _show_candidate(candidate, aliases[_excerpt_key(candidate)], output_stream, language)
        answer = _read_line(
            localized(
                language,
                "Include this source excerpt? [y/N]: ",
                "이 소스 발췌를 포함할까요? [y/N]: ",
            ),
            input_stream,
            output_stream,
        )
        if answer not in {"", "n", "y"}:
            raise SourceReviewError(
                localized(
                    language,
                    "source answer must be y, n, or blank",
                    "소스 응답은 y, n 또는 빈 입력이어야 합니다",
                )
            )
        if answer != "y":
            continue
        try:
            approved = prepare_source_excerpts((*approved, candidate))
        except SourceExcerptLimitError as error:
            reason = escape_terminal_line(str(error))
            _write(
                output_stream,
                localized(
                    language,
                    f"Source excerpt skipped: {reason}\n",
                    f"소스 발췌를 건너뜀: {reason}\n",
                ),
            )

    exposed = tuple(
        sorted({alias for excerpt in approved for alias in aliases[_excerpt_key(excerpt)]})
    )
    if exposed:
        visible_aliases = ", ".join(escape_terminal_line(alias) for alias in exposed)
        _write(
            output_stream,
            localized(
                language,
                f"Boundary aliases exposed in approved source: {visible_aliases}\n",
                f"승인한 소스에 노출되는 경계 별칭: {visible_aliases}\n",
            ),
        )
        if (
            _read_line(
                localized(
                    language,
                    "Type exactly EXPOSE to include boundary identifiers: ",
                    "경계 식별자를 포함하려면 EXPOSE를 정확히 입력하세요: ",
                ),
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
            | {
                disclosure.placeholder.alias
                for disclosure in index.boundary_disclosures
                if disclosure.node_id in included
            }
        )
    )


def _show_candidate(
    excerpt: SourceExcerpt,
    aliases: tuple[str, ...],
    output: TextIO,
    language: Language,
) -> None:
    path = escape_terminal_line(excerpt.path)
    qualified_name = escape_terminal_line(excerpt.qualified_name)
    visible_aliases = ", ".join(escape_terminal_line(alias) for alias in aliases)
    korean_kind = {"module": "파일(모듈)", "class": "클래스", "function": "함수"}[excerpt.kind]
    _write(
        output,
        localized(
            language,
            f"Source candidate: {path} | {excerpt.kind} {qualified_name} | "
            f"lines {excerpt.start_line}-{excerpt.end_line}\n"
            f"Boundary aliases: {visible_aliases if aliases else 'none'}\n"
            "```python\n",
            f"소스 후보: {path} | {korean_kind} {qualified_name} | "
            f"{excerpt.start_line}-{excerpt.end_line}행\n"
            f"경계 별칭: {visible_aliases if aliases else '없음'}\n"
            "```python\n",
        ),
    )
    _write(output, escape_terminal_preview(excerpt.content))
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
