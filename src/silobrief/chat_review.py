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
    ReviewNode,
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
from silobrief.terminal import styled, supports_color


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
    related = _related_candidates(index, options, selected_numbers)
    if selected_numbers:
        _show_related_candidates(related, output_stream, cli_language)
    added = _read_additions(
        index,
        options,
        selected_numbers,
        related,
        input_stream,
        output_stream,
        cli_language,
    )
    excluded = _read_selectors(
        localized(
            cli_language,
            "File path or unique ID to leave out of the brief",
            "문서에서 뺄 파일 경로나 고유 ID",
        ),
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
    _show_selected_context(selection, output_stream, cli_language)
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
    _write(
        output,
        render_candidate_results(
            options,
            language=language,
            color=supports_color(output),
            interactive=True,
        ),
    )


def _confirm_request(input_stream: TextIO, output_stream: TextIO, language: Language) -> None:
    notice = styled(
        localized(language, "[Notice]", "[주의]"),
        "1;33",
        enabled=supports_color(output_stream),
    )
    _write(
        output_stream,
        f"{notice} "
        + localized(
            language,
            "Your prompt works best when it includes:\n"
            "- the goal of the task\n"
            "- the output you need\n"
            "- how you will decide it is complete\n\n",
            "프롬프트에는 다음 내용이 들어가면 좋습니다:\n"
            "- 작업 목표\n"
            "- 필요한 결과물\n"
            "- 완료 또는 승인 기준\n\n",
        ),
    )
    if (
        _read_line(
            localized(
                language,
                "Continue with this prompt? [y/N]: ",
                "이 프롬프트로 계속할까요? [y/N]: ",
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
        localized(
            language,
            "Candidate numbers to include (example: 1 3, Enter to search by path): ",
            "포함할 후보 번호 (예: 1 3, 파일 경로로 찾으려면 Enter): ",
        ),
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
    candidates: tuple[CandidateOption, ...],
    selected_numbers: tuple[int, ...],
    related: tuple[ReviewNode, ...],
    input_stream: TextIO,
    output_stream: TextIO,
    language: Language,
) -> tuple[str, ...]:
    selectors: list[str] = []
    direct_selectors: list[str] = []
    current_related = related
    if current_related:
        _write(
            output_stream,
            localized(
                language,
                "Enter one r-number at a time. You can also enter a file path or unique ID.\n",
                "r번호를 하나씩 입력하세요. 목록에 없으면 파일 경로나 고유 ID를 "
                "입력할 수 있습니다.\n",
            ),
        )
    while selector := _read_line(
        _addition_prompt(current_related, language), input_stream, output_stream
    ):
        related_id = _related_selector(selector, current_related, language)
        if related_id is not None:
            selectors.append(related_id)
            continue
        try:
            symbol_options = selector_symbol_options(index, selector)
        except ReviewError as error:
            raise ChatReviewError(str(error)) from error
        if symbol_options is None:
            selectors.append(selector)
            direct_selectors.append(selector)
        else:
            _show_symbol_options(selector, symbol_options, output_stream, language)
            numbers = _read_symbol_numbers(input_stream, output_stream, language)
            if not numbers:
                selectors.append(selector)
                direct_selectors.append(selector)
            for number in numbers:
                if number > len(symbol_options):
                    raise ChatReviewError(
                        localized(
                            language,
                            f"unknown symbol number: {number}",
                            f"알 수 없는 함수 또는 클래스 번호: {number}",
                        )
                    )
                node_id = symbol_options[number - 1].node.id
                selectors.append(node_id)
                direct_selectors.append(node_id)
        updated_related = _related_candidates(
            index,
            candidates,
            selected_numbers,
            tuple(direct_selectors),
        )
        if updated_related != current_related:
            current_related = updated_related
            _show_related_candidates(current_related, output_stream, language)
    return tuple(selectors)


def _related_selector(
    selector: str,
    related: tuple[ReviewNode, ...],
    language: Language,
) -> str | None:
    if not (selector.startswith("r") and selector[1:].isdigit()):
        return None
    number = int(selector[1:])
    if number < 1 or number > len(related):
        raise ChatReviewError(
            localized(
                language,
                f"unknown related candidate: {selector}",
                f"알 수 없는 추가 코드 번호: {selector}",
            )
        )
    return related[number - 1].id


def _addition_prompt(related: tuple[ReviewNode, ...], language: Language) -> str:
    if related:
        return localized(
            language,
            "Code to add (example: r1, Enter to finish): ",
            "추가할 코드 (예: r1, 끝내려면 Enter): ",
        )
    return localized(
        language,
        "File path or unique ID to add (Enter to finish): ",
        "추가할 파일 경로나 고유 ID (끝내려면 Enter): ",
    )


def _show_symbol_options(
    path: str,
    options: tuple[SymbolOption, ...],
    output: TextIO,
    language: Language,
) -> None:
    _write(
        output,
        localized(
            language,
            f"Functions and classes in `{path}`:\n",
            f"`{path}`에서 선택할 함수와 클래스:\n",
        ),
    )
    if not options:
        _write(output, localized(language, "- none\n", "- 없음\n"))
    for option in options:
        _write(
            output,
            f"{option.number}. {_kind_label(option.node.kind, language)} "
            f"{option.node.qualified_name}\n",
        )


def _read_symbol_numbers(
    input_stream: TextIO, output_stream: TextIO, language: Language
) -> tuple[int, ...]:
    value = _read_line(
        localized(
            language,
            "Select function or class numbers to include their source code "
            "(press Enter to include file details only, without source code): ",
            "소스코드를 포함할 함수나 클래스 번호를 선택하세요 "
            "(소스코드 없이 파일 정보만 포함하려면 Enter): ",
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
                "함수 또는 클래스 번호는 공백으로 구분한 양의 정수여야 합니다",
            )
        ) from error
    if any(number < 1 for number in numbers):
        raise ChatReviewError(
            localized(
                language,
                "symbol numbers must be space-separated positive integers",
                "함수 또는 클래스 번호는 공백으로 구분한 양의 정수여야 합니다",
            )
        )
    return numbers


def _related_candidates(
    index: IndexData,
    options: tuple[CandidateOption, ...],
    selected_numbers: tuple[int, ...],
    added: tuple[str, ...] = (),
) -> tuple[ReviewNode, ...]:
    if not selected_numbers and not added:
        return ()
    try:
        return review_selection(
            index,
            options,
            selected_numbers=selected_numbers,
            added=added,
            excluded=(),
            fields=_NO_FIELDS,
        ).expanded
    except ReviewError as error:
        raise ChatReviewError(str(error)) from error


def _show_related_candidates(
    related: tuple[ReviewNode, ...], output: TextIO, language: Language
) -> None:
    color = supports_color(output)
    _write(
        output,
        styled(
            localized(
                language,
                "Other code connected to your selection (optional):\n",
                "함께 확인할 코드 (선택 사항):\n",
            ),
            "1;36",
            enabled=color,
        ),
    )
    if not related:
        _write(
            output,
            localized(
                language,
                "No directly connected code was found.\n",
                "직접 연결된 다른 코드를 찾지 못했습니다.\n",
            ),
        )
        return
    _write(
        output,
        localized(
            language,
            "These items are directly connected to your selection through function calls, "
            "references, imports, or class and file membership. They are not in the brief yet. "
            "Add only what you need.\n\n",
            "방금 고른 코드와 호출, 참조, import 또는 포함 관계로 직접 연결된 항목입니다. "
            "아직 문서에는 들어가지 않았습니다. 필요한 코드만 추가하세요.\n\n",
        ),
    )
    for number, node in enumerate(related, start=1):
        _write(
            output,
            f"{styled(f'[r{number}]', '1;32', enabled=color)} "
            f"{_kind_label(node.kind, language)} "
            f"{styled(node.qualified_name, '1', enabled=color)}\n"
            f"     {localized(language, 'File', '파일')}: {node.path}\n"
            f"     {localized(language, 'Relationship', '선택한 코드와의 관계')}: "
            f"{_relation_labels(node.relations, node.kind, language)}\n\n",
        )


def _show_selected_context(selection: ReviewSelection, output: TextIO, language: Language) -> None:
    _write(output, localized(language, "Code selected for the brief:\n", "문서에 넣을 코드:\n"))
    for node in selection.selected:
        _write(
            output,
            f"- {_kind_label(node.kind, language)} {node.qualified_name} ({node.path})\n",
        )


def _read_fields(
    input_stream: TextIO, output_stream: TextIO, language: Language
) -> DisclosureChoices:
    return DisclosureChoices(
        paths=_read_choice(
            localized(
                language,
                "Include selected file paths?",
                "선택한 코드의 파일 경로를 문서에 포함할까요?",
            ),
            input_stream,
            output_stream,
            language,
        ),
        symbols=_read_choice(
            localized(
                language,
                "Include selected function and class names?",
                "선택한 함수와 클래스 이름을 문서에 포함할까요?",
            ),
            input_stream,
            output_stream,
            language,
        ),
        public_libraries=_read_choice(
            localized(
                language,
                "Include public library names?",
                "사용한 공개 라이브러리 이름을 문서에 포함할까요?",
            ),
            input_stream,
            output_stream,
            language,
        ),
        human_notes=_read_choice(
            localized(
                language,
                "Include notes saved with sb log?",
                "sb log로 저장한 메모를 문서에 포함할까요?",
            ),
            input_stream,
            output_stream,
            language,
        ),
        boundary_placeholders=_read_choice(
            localized(
                language,
                "Include public boundary descriptions saved with sb ignore?",
                "sb ignore로 저장한 공개용 경계 설명을 문서에 포함할까요?",
            ),
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


def _kind_label(kind: str, language: Language) -> str:
    labels = {
        "module": localized(language, "module", "파일(모듈)"),
        "class": localized(language, "class", "클래스"),
        "function": localized(language, "function", "함수"),
    }
    return labels[kind]


def _relation_labels(relations: tuple[str, ...], kind: str, language: Language) -> str:
    english_noun = {
        "module": "this module",
        "class": "this class",
        "function": "this function",
    }[kind]
    korean_object = {
        "module": "이 파일(모듈)을",
        "class": "이 클래스를",
        "function": "이 함수를",
    }[kind]
    korean_subject = {
        "module": "이 파일(모듈)이",
        "class": "이 클래스가",
        "function": "이 함수가",
    }[kind]
    labels = {
        "calls": localized(
            language,
            f"the selected code calls {english_noun}",
            f"선택한 코드가 {korean_object} 호출함",
        ),
        "called-by": localized(
            language,
            f"{english_noun} calls the selected code",
            f"{korean_subject} 선택한 코드를 호출함",
        ),
        "imports": localized(
            language,
            f"the selected code imports {english_noun}",
            f"선택한 코드가 {korean_object} 불러옴(import)",
        ),
        "imported-by": localized(
            language,
            f"{english_noun} imports the selected code",
            f"{korean_subject} 선택한 코드를 불러옴(import)",
        ),
        "references": localized(
            language,
            f"the selected code refers to {english_noun}",
            f"선택한 코드가 {korean_object} 참조함",
        ),
        "referenced-by": localized(
            language,
            f"{english_noun} refers to the selected code",
            f"{korean_subject} 선택한 코드를 참조함",
        ),
        "contains": localized(
            language,
            f"the selected code contains {english_noun}",
            f"선택한 코드가 {korean_object} 포함함",
        ),
        "contained-by": localized(
            language,
            f"{english_noun} contains the selected code",
            f"{korean_subject} 선택한 코드를 포함함",
        ),
    }
    return "; ".join(labels[relation] for relation in relations)


def _brief_input(
    prompt: str,
    index: IndexData,
    notes: NotesData,
    selection: ReviewSelection,
    *,
    source_excerpts: tuple[ApprovedSourceExcerpt, ...] = (),
) -> BriefInput:
    nodes = selection.selected
    node_ids = {node.id for node in nodes}
    included_ids, enclosing_ids = _source_context_ids(index, node_ids)
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
        public_imports=(
            _public_imports(index, included_ids, enclosing_ids) if choices.public_libraries else ()
        ),
        human_notes=_human_notes(notes, paths) if choices.human_notes else (),
        boundaries=_boundaries(index, included_ids) if choices.boundary_placeholders else (),
        source_excerpts=source_excerpts,
    )


def _source_context_ids(index: IndexData, node_ids: set[str]) -> tuple[set[str], set[str]]:
    included = set(node_ids)
    while descendants := {
        edge.target_id
        for edge in index.edges
        if edge.kind == "contains"
        and edge.source_id in included
        and edge.target_id is not None
        and edge.target_id not in included
    }:
        included.update(descendants)

    enclosing: set[str] = set()
    frontier = set(node_ids)
    while parents := {
        edge.source_id
        for edge in index.edges
        if edge.kind == "contains"
        and edge.target_id in frontier
        and edge.source_id not in included
        and edge.source_id not in enclosing
    }:
        enclosing.update(parents)
        frontier = parents
    return included, enclosing


def _public_imports(
    index: IndexData,
    included_ids: set[str],
    enclosing_ids: set[str],
) -> tuple[str, ...]:
    used_targets = {
        edge.target
        for edge in index.edges
        if edge.source_id in included_ids
        and edge.kind in {"call", "reference"}
        and edge.target_id is None
        and isinstance(edge.target, str)
    }
    import_source_ids = included_ids | enclosing_ids
    return tuple(
        sorted(
            {
                edge.target
                for edge in index.edges
                if edge.source_id in import_source_ids
                and edge.kind == "import"
                and edge.target_id is None
                and isinstance(edge.target, str)
                and not edge.target.startswith(".")
                and any(
                    target == edge.target or target.startswith(f"{edge.target}.")
                    for target in used_targets
                )
            }
        )
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
