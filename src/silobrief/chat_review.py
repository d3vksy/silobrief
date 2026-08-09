from __future__ import annotations

from typing import TextIO

from silobrief.boundary_placeholders import BoundaryPlaceholder
from silobrief.candidate_search import (
    CandidateSearchError,
    render_candidate_results,
    search_candidates,
)
from silobrief.index import IndexData
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
) -> RenderedBrief:
    if not prompt.strip():
        raise ChatReviewError("request must not be empty")
    if not input_stream.isatty() or not output_stream.isatty():
        raise ChatReviewError("review requires an interactive terminal")
    if not index.nodes:
        raise ChatReviewError(
            "no indexed Python symbols are available; "
            "siloBrief currently supports Python projects only"
        )
    _confirm_request(input_stream, output_stream)

    try:
        options = search_candidates(prompt, index, notes)
    except CandidateSearchError as error:
        raise ChatReviewError(str(error)) from error
    _show_candidates(options, output_stream)
    selected_numbers = _read_numbers(input_stream, output_stream)
    added = _read_additions(index, input_stream, output_stream)
    excluded = _read_selectors("Exclude path or node ID", input_stream, output_stream)
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
    _show_selection(selection, output_stream)
    reviewed = ReviewSelection(
        selection.selected, selection.expanded, _read_fields(input_stream, output_stream)
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
            )
        )
    except RenderError as error:
        raise ChatReviewError(str(error)) from error


def _show_candidates(options: tuple[CandidateOption, ...], output: TextIO) -> None:
    _write(output, render_candidate_results(options))


def _confirm_request(input_stream: TextIO, output_stream: TextIO) -> None:
    _write(
        output_stream,
        "Request completeness:\n"
        "- work goal\n"
        "- required deliverables\n"
        "- completion or acceptance criteria\n",
    )
    if (
        _read_line("Continue with this complete request? [y/N]: ", input_stream, output_stream)
        != "y"
    ):
        raise ChatReviewError("request completeness was not confirmed")


def _read_numbers(input_stream: TextIO, output_stream: TextIO) -> tuple[int, ...]:
    value = _read_line("Select candidate numbers: ", input_stream, output_stream)
    if not value:
        return ()
    try:
        return tuple(int(part) for part in value.split())
    except ValueError as error:
        raise ChatReviewError("candidate numbers must be space-separated integers") from error


def _read_selectors(label: str, input_stream: TextIO, output_stream: TextIO) -> tuple[str, ...]:
    values: list[str] = []
    while value := _read_line(f"{label} (blank to finish): ", input_stream, output_stream):
        values.append(value)
    return tuple(values)


def _read_additions(
    index: IndexData,
    input_stream: TextIO,
    output_stream: TextIO,
) -> tuple[str, ...]:
    selectors: list[str] = []
    while selector := _read_line(
        "Add path or node ID (blank to finish): ", input_stream, output_stream
    ):
        try:
            options = selector_symbol_options(index, selector)
        except ReviewError as error:
            raise ChatReviewError(str(error)) from error
        if options is None:
            selectors.append(selector)
            continue
        _show_symbol_options(selector, options, output_stream)
        numbers = _read_symbol_numbers(input_stream, output_stream)
        if not numbers:
            selectors.append(selector)
            continue
        for number in numbers:
            if number > len(options):
                raise ChatReviewError(f"unknown symbol number: {number}")
            selectors.append(options[number - 1].node.id)
    return tuple(selectors)


def _show_symbol_options(
    path: str,
    options: tuple[SymbolOption, ...],
    output: TextIO,
) -> None:
    _write(output, f"Symbols in `{path}`:\n")
    if not options:
        _write(output, "- none\n")
    for option in options:
        _write(output, f"{option.number}. {option.node.kind} {option.node.qualified_name}\n")


def _read_symbol_numbers(input_stream: TextIO, output_stream: TextIO) -> tuple[int, ...]:
    value = _read_line(
        "Select symbol numbers from this file (blank for module only): ",
        input_stream,
        output_stream,
    )
    if not value:
        return ()
    try:
        numbers = tuple(int(part) for part in value.split())
    except ValueError as error:
        raise ChatReviewError("symbol numbers must be space-separated positive integers") from error
    if any(number < 1 for number in numbers):
        raise ChatReviewError("symbol numbers must be space-separated positive integers")
    return numbers


def _show_selection(selection: ReviewSelection, output: TextIO) -> None:
    for label, nodes in (
        ("Selected context", selection.selected),
        ("Expanded context", selection.expanded),
    ):
        _write(output, f"{label}:\n")
        if not nodes:
            _write(output, "- none\n")
        for node in nodes:
            _write(output, f"- {node.path} | {node.kind} {node.qualified_name}\n")


def _read_fields(input_stream: TextIO, output_stream: TextIO) -> DisclosureChoices:
    return DisclosureChoices(
        paths=_read_choice("Include relative paths?", input_stream, output_stream),
        symbols=_read_choice("Include symbols?", input_stream, output_stream),
        public_libraries=_read_choice("Include public libraries?", input_stream, output_stream),
        human_notes=_read_choice("Include human notes?", input_stream, output_stream),
        boundary_placeholders=_read_choice(
            "Include boundary placeholders?", input_stream, output_stream
        ),
    )


def _read_choice(label: str, input_stream: TextIO, output_stream: TextIO) -> bool:
    value = _read_line(f"{label} [y/n]: ", input_stream, output_stream)
    if value not in {"y", "n"}:
        raise ChatReviewError("field answer must be exactly y or n")
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
