from __future__ import annotations

from silobrief.index import IndexData
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


def render_candidate_results(options: tuple[CandidateOption, ...]) -> str:
    lines = ["Candidates:"]
    if not options:
        lines.append("- none")
    for option in options:
        node = option.node
        lines.append(
            f"{option.number}. {node.path} | {node.kind} {node.qualified_name} "
            f"| score={option.score}"
        )
        lines.append(f"   matches: {_render_matches(option.evidence)}")
        lines.append(f"   connections: {option.evidence.connected_nodes}")
    return "\n".join(lines) + "\n"


def _render_matches(evidence: RankEvidence) -> str:
    fields = (
        ("path", evidence.path_matches),
        ("symbol", evidence.symbol_matches),
        ("import", evidence.import_matches),
        ("docstring", evidence.docstring_matches),
        ("comment", evidence.comment_matches),
        ("note", evidence.note_matches),
    )
    matches = [f"{label}={','.join(tokens)}" for label, tokens in fields if tokens]
    return "; ".join(matches) if matches else "none"
