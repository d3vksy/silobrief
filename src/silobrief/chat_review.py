from __future__ import annotations

from typing import TextIO

from silobrief.boundary_placeholders import BoundaryPlaceholder
from silobrief.candidate_search import (
    CandidateSearchError,
    render_candidate_results,
    search_candidates,
)
from silobrief.index import IndexData
from silobrief.language import Language, localized
from silobrief.renderer import (
    ApprovedBoundary,
    ApprovedSymbol,
    BriefInput,
    RenderedBrief,
    RenderError,
    render_brief,
)
from silobrief.review import (
    CandidateOption,
    DisclosureChoices,
    ReviewError,
    ReviewSelection,
    SymbolOption,
    review_selection,
    selector_symbol_options,
)
from silobrief.source_review import (
    ApprovedSourceExcerpt,
    SourceReviewError,
    review_source_disclosure,
)
from silobrief.sources import SourceSnapshot
from silobrief.state import NotesData


class ChatReviewError(ValueError):
    pass


_NO_FIELDS = DisclosureChoices(False, False, False, False, False)


def review_brief(
    prompt: str,
    index: IndexData,
    notes: NotesData,
    *,
    input_stream: TextIO,
    output_stream: TextIO,
    snapshot: SourceSnapshot | None = None,
    brief_language: Language = "en",
    cli_language: Language = "en",
) -> RenderedBrief:
    if not prompt.strip():
        raise ChatReviewError(
            localized(cli_language, "request must not be empty", "요청은 비어 있을 수 없습니다")
        )
    if not input_stream.isatty() or not output_stream.isatty():
        raise ChatReviewError(
            localized(
                cli_language,
                "review requires an interactive terminal",
                "검토에는 대화형 터미널이 필요합니다",
            )
        )
    if not index.nodes:
        raise ChatReviewError(
            localized(
                cli_language,
                "no indexed Python symbols are available; "
                "siloBrief currently supports Python projects only",
                "인덱스에 Python 심볼이 없습니다. siloBrief는 현재 Python 프로젝트만 지원합니다",
            )
        )
    _confirm_request(input_stream, output_stream, cli_language)

    try:
        options = search_candidates(prompt, index, notes)
    except CandidateSearchError as error:
        raise ChatReviewError(str(error)) from error
    _show_candidates(options, output_stream, cli_language)
    selected_numbers = _read_numbers(input_stream, output_stream, cli_language)
    added = _read_additions(index, input_stream, output_stream, cli_language)
    excluded = _read_selectors(
        localized(cli_language, "Exclude path or node ID", "제외할 경로 또는 노드 ID"),
        input_stream,
        output_stream,
        cli_language,
    )
    try:
        selection = review_selection(
            index,
            options,
            selected_numbers=selected_numbers,
            added=added,
            excluded=excluded,
            fields=_NO_FIELDS,
        )
    except ReviewError as error:
        raise ChatReviewError(str(error)) from error
    _show_selection(selection, output_stream, cli_language)
    reviewed = ReviewSelection(
        selection.selected,
        selection.expanded,
        _read_fields(input_stream, output_stream, cli_language),
    )

    approved_sources: tuple[ApprovedSourceExcerpt, ...] = ()
    if snapshot is not None:
        try:
            approved_sources = review_source_disclosure(
                index,
                snapshot,
                reviewed,
                input_stream=input_stream,
                output_stream=output_stream,
                language=cli_language,
            )
        except SourceReviewError as error:
            raise ChatReviewError(str(error)) from error
    try:
        return render_brief(
            _brief_input(
                prompt,
                index,
                notes,
                reviewed,
                source_excerpts=approved_sources,
            ),
            language=brief_language,
        )
    except RenderError as error:
        raise ChatReviewError(str(error)) from error


def _show_candidates(
    options: tuple[CandidateOption, ...], output: TextIO, language: Language
) -> None:
    _write(output, render_candidate_results(options, language=language))


def _confirm_request(input_stream: TextIO, output_stream: TextIO, language: Language) -> None:
    _write(
        output_stream,
        localized(
            language,
            "Request completeness:\n"
            "- work goal\n"
            "- required deliverables\n"
            "- completion or acceptance criteria\n",
            "요청 내용 확인:\n- 작업 목표\n- 필요한 결과물\n- 완료 또는 승인 기준\n",
        ),
    )
    if (
        _read_line(
            localized(
                language,
                "Continue with this complete request? [y/N]: ",
                "이 요청으로 계속할까요? [y/N]: ",
            ),
            input_stream,
            output_stream,
        )
        != "y"
    ):
        raise ChatReviewError(
            localized(
                language,
                "request completeness was not confirmed",
                "요청 내용이 확인되지 않았습니다",
            )
        )


def _read_numbers(
    input_stream: TextIO, output_stream: TextIO, language: Language
) -> tuple[int, ...]:
    value = _read_line(
        localized(language, "Select candidate numbers: ", "후보 번호를 선택하세요: "),
        input_stream,
        output_stream,
    )
    if not value:
        return ()
    try:
        return tuple(int(part) for part in value.split())
    except ValueError as error:
        raise ChatReviewError(
            localized(
                language,
                "candidate numbers must be space-separated integers",
                "후보 번호는 공백으로 구분한 정수여야 합니다",
            )
        ) from error


def _read_selectors(
    label: str,
    input_stream: TextIO,
    output_stream: TextIO,
    language: Language,
) -> tuple[str, ...]:
    values: list[str] = []
    suffix = localized(language, " (blank to finish): ", " (끝내려면 Enter): ")
    while value := _read_line(f"{label}{suffix}", input_stream, output_stream):
        values.append(value)
    return tuple(values)


def _read_additions(
    index: IndexData,
    input_stream: TextIO,
    output_stream: TextIO,
    language: Language,
) -> tuple[str, ...]:
    selectors: list[str] = []
    while selector := _read_line(
        localized(
            language,
            "Add path or node ID (blank to finish): ",
            "추가할 경로 또는 노드 ID (끝내려면 Enter): ",
        ),
        input_stream,
        output_stream,
    ):
        try:
            options = selector_symbol_options(index, selector)
        except ReviewError as error:
            raise ChatReviewError(str(error)) from error
        if options is None:
            selectors.append(selector)
            continue
        _show_symbol_options(selector, options, output_stream, language)
        numbers = _read_symbol_numbers(input_stream, output_stream, language)
        if not numbers:
            selectors.append(selector)
            continue
        for number in numbers:
            if number > len(options):
                raise ChatReviewError(
                    localized(
                        language,
                        f"unknown symbol number: {number}",
                        f"알 수 없는 심볼 번호: {number}",
                    )
                )
            selectors.append(options[number - 1].node.id)
    return tuple(selectors)


def _show_symbol_options(
    path: str,
    options: tuple[SymbolOption, ...],
    output: TextIO,
    language: Language,
) -> None:
    _write(
        output,
        localized(language, f"Symbols in `{path}`:\n", f"`{path}`의 심볼:\n"),
    )
    if not options:
        _write(output, localized(language, "- none\n", "- 없음\n"))
    for option in options:
        _write(output, f"{option.number}. {option.node.kind} {option.node.qualified_name}\n")


def _read_symbol_numbers(
    input_stream: TextIO, output_stream: TextIO, language: Language
) -> tuple[int, ...]:
    value = _read_line(
        localized(
            language,
            "Select symbol numbers from this file (blank for module only): ",
            "이 파일에서 심볼 번호를 선택하세요 (모듈만 고르려면 Enter): ",
        ),
        input_stream,
        output_stream,
    )
    if not value:
        return ()
    try:
        numbers = tuple(int(part) for part in value.split())
    except ValueError as error:
        raise ChatReviewError(
            localized(
                language,
                "symbol numbers must be space-separated positive integers",
                "심볼 번호는 공백으로 구분한 양의 정수여야 합니다",
            )
        ) from error
    if any(number < 1 for number in numbers):
        raise ChatReviewError(
            localized(
                language,
                "symbol numbers must be space-separated positive integers",
                "심볼 번호는 공백으로 구분한 양의 정수여야 합니다",
            )
        )
    return numbers


def _show_selection(selection: ReviewSelection, output: TextIO, language: Language) -> None:
    for label, nodes in (
        (localized(language, "Selected context", "선택한 맥락"), selection.selected),
        (localized(language, "Expanded context", "확장된 맥락"), selection.expanded),
    ):
        _write(output, f"{label}:\n")
        if not nodes:
            _write(output, localized(language, "- none\n", "- 없음\n"))
        for node in nodes:
            _write(output, f"- {node.path} | {node.kind} {node.qualified_name}\n")


def _read_fields(
    input_stream: TextIO, output_stream: TextIO, language: Language
) -> DisclosureChoices:
    return DisclosureChoices(
        paths=_read_choice(
            localized(language, "Include relative paths?", "상대 경로를 포함할까요?"),
            input_stream,
            output_stream,
            language,
        ),
        symbols=_read_choice(
            localized(language, "Include symbols?", "심볼을 포함할까요?"),
            input_stream,
            output_stream,
            language,
        ),
        public_libraries=_read_choice(
            localized(language, "Include public libraries?", "공개 라이브러리를 포함할까요?"),
            input_stream,
            output_stream,
            language,
        ),
        human_notes=_read_choice(
            localized(language, "Include human notes?", "사용자 메모를 포함할까요?"),
            input_stream,
            output_stream,
            language,
        ),
        boundary_placeholders=_read_choice(
            localized(language, "Include boundary placeholders?", "경계 정보를 포함할까요?"),
            input_stream,
            output_stream,
            language,
        ),
    )


def _read_choice(
    label: str, input_stream: TextIO, output_stream: TextIO, language: Language
) -> bool:
    value = _read_line(f"{label} [y/n]: ", input_stream, output_stream)
    if value not in {"y", "n"}:
        raise ChatReviewError(
            localized(
                language,
                "field answer must be exactly y or n",
                "항목 응답은 정확히 y 또는 n이어야 합니다",
            )
        )
    return value == "y"


def _read_line(label: str, input_stream: TextIO, output_stream: TextIO) -> str:
    _write(output_stream, label)
    try:
        output_stream.flush()
        return input_stream.readline().rstrip("\r\n")
    except OSError as error:
        raise ChatReviewError("interactive terminal input failed") from error


def _write(output: TextIO, value: str) -> None:
    try:
        output.write(value)
    except OSError as error:
        raise ChatReviewError("interactive terminal output failed") from error


def _brief_input(
    prompt: str,
    index: IndexData,
    notes: NotesData,
    selection: ReviewSelection,
    *,
    source_excerpts: tuple[ApprovedSourceExcerpt, ...] = (),
) -> BriefInput:
    nodes = (*selection.selected, *selection.expanded)
    node_ids = {node.id for node in nodes}
    paths = {node.path for node in nodes}
    choices = selection.fields
    return BriefInput(
        user_prompt=prompt,
        relative_paths=tuple(node.path for node in nodes) if choices.paths else (),
        symbols=(
            tuple(ApprovedSymbol(node.kind, node.qualified_name) for node in nodes)
            if choices.symbols
            else ()
        ),
        public_imports=_public_imports(index, node_ids) if choices.public_libraries else (),
        human_notes=_human_notes(notes, paths) if choices.human_notes else (),
        boundaries=_boundaries(index, node_ids) if choices.boundary_placeholders else (),
        source_excerpts=source_excerpts,
    )


def _public_imports(index: IndexData, node_ids: set[str]) -> tuple[str, ...]:
    return tuple(
        edge.target
        for edge in index.edges
        if edge.source_id in node_ids
        and edge.kind == "import"
        and edge.target_id is None
        and isinstance(edge.target, str)
        and not edge.target.startswith(".")
    )


def _human_notes(notes: NotesData, paths: set[str]) -> tuple[str, ...]:
    return tuple(
        note["comment"]
        for note in notes["notes"]
        if any(
            note["path"] == "." or path == note["path"] or path.startswith(f"{note['path']}/")
            for path in paths
        )
    )


def _boundaries(index: IndexData, node_ids: set[str]) -> tuple[ApprovedBoundary, ...]:
    return tuple(
        ApprovedBoundary(edge.target.alias, edge.target.description)
        for edge in index.edges
        if edge.source_id in node_ids and isinstance(edge.target, BoundaryPlaceholder)
    )
