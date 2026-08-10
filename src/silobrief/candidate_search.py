from __future__ import annotations

from silobrief.index import IndexData
from silobrief.language import Language, localized
from silobrief.ranking import RankEvidence, rank_candidates
from silobrief.review import CandidateOption, ReviewError, candidate_options
from silobrief.state import NotesData


class CandidateSearchError(ValueError):
    pass


def search_candidates(
    prompt: str,
    index: IndexData,
    notes: NotesData,
) -> tuple[CandidateOption, ...]:
    if not prompt.strip():
        raise CandidateSearchError("request must not be empty")
    try:
        return candidate_options(rank_candidates(prompt, index, notes))
    except ReviewError as error:
        raise CandidateSearchError(str(error)) from error


def render_candidate_results(
    options: tuple[CandidateOption, ...], *, language: Language = "en"
) -> str:
    lines = [localized(language, "Candidates:", "후보:")]
    if not options:
        lines.append(localized(language, "- none", "- 없음"))
    for option in options:
        node = option.node
        lines.append(
            f"{option.number}. {node.path} | {node.kind} {node.qualified_name} "
            f"| score={option.score}"
        )
        lines.append(
            f"   {localized(language, 'matches', '일치 항목')}: "
            f"{_render_matches(option.evidence, language=language)}"
        )
        lines.append(
            f"   {localized(language, 'connections', '연결 수')}: {option.evidence.connected_nodes}"
        )
    return "\n".join(lines) + "\n"


def _render_matches(evidence: RankEvidence, *, language: Language) -> str:
    fields = (
        (localized(language, "path", "경로"), evidence.path_matches),
        (localized(language, "symbol", "심볼"), evidence.symbol_matches),
        ("import", evidence.import_matches),
        ("docstring", evidence.docstring_matches),
        (localized(language, "comment", "주석"), evidence.comment_matches),
        (localized(language, "note", "메모"), evidence.note_matches),
    )
    matches = [f"{label}={','.join(tokens)}" for label, tokens in fields if tokens]
    return "; ".join(matches) if matches else localized(language, "none", "없음")
