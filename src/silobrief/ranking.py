from __future__ import annotations

from dataclasses import dataclass

from silobrief.index import IndexData, IndexNode
from silobrief.search_tokens import normalize_search_tokens
from silobrief.state import HumanNoteData, NotesData

_SYMBOL_WEIGHT = 5
_PATH_WEIGHT = 4
_IMPORT_WEIGHT = 3
_DOCSTRING_WEIGHT = 2
_COMMENT_WEIGHT = 1
_NOTE_WEIGHT = 4
_MAX_CONNECTIVITY_SCORE = 3
_MAX_CANDIDATES = 10


@dataclass(frozen=True, slots=True)
class RankEvidence:
    path_matches: int
    symbol_matches: int
    import_matches: int
    docstring_matches: int
    comment_matches: int
    note_match: bool
    connected_nodes: int


@dataclass(frozen=True, slots=True)
class RankedCandidate:
    node: IndexNode
    score: int
    evidence: RankEvidence


def rank_candidates(
    prompt: str,
    index: IndexData,
    notes: NotesData,
) -> tuple[RankedCandidate, ...]:
    query = frozenset(normalize_search_tokens(prompt))
    if not query:
        return ()

    adjacency = _adjacency(index)
    note_tokens = tuple(
        (note, frozenset(normalize_search_tokens(note["comment"]))) for note in notes["notes"]
    )
    candidates: list[RankedCandidate] = []
    for candidate in index.nodes:
        evidence = _evidence(candidate, query, adjacency, note_tokens)
        if not _has_text_match(evidence):
            continue
        candidates.append(
            RankedCandidate(
                node=candidate,
                score=_score(evidence),
                evidence=evidence,
            )
        )
    candidates.sort(key=_candidate_key)
    return tuple(candidates[:_MAX_CANDIDATES])


def _evidence(
    node: IndexNode,
    query: frozenset[str],
    adjacency: dict[str, frozenset[str]],
    note_tokens: tuple[tuple[HumanNoteData, frozenset[str]], ...],
) -> RankEvidence:
    return RankEvidence(
        path_matches=_match_count(query, node.tokens.path),
        symbol_matches=_match_count(query, node.tokens.symbol),
        import_matches=_match_count(query, node.tokens.imports),
        docstring_matches=_match_count(query, node.tokens.docstrings),
        comment_matches=_match_count(query, node.tokens.comments),
        note_match=any(
            _note_applies(note["path"], node.path) and not query.isdisjoint(tokens)
            for note, tokens in note_tokens
        ),
        connected_nodes=len(adjacency.get(node.id, ())),
    )


def _adjacency(index: IndexData) -> dict[str, frozenset[str]]:
    node_ids = {node.id for node in index.nodes}
    neighbors: dict[str, set[str]] = {node_id: set() for node_id in node_ids}
    for edge in index.edges:
        target_id = edge.target_id
        if (
            edge.source_id not in node_ids
            or target_id not in node_ids
            or edge.source_id == target_id
        ):
            continue
        neighbors[edge.source_id].add(target_id)
        neighbors[target_id].add(edge.source_id)
    return {node_id: frozenset(values) for node_id, values in neighbors.items()}


def _note_applies(note_path: str, node_path: str) -> bool:
    return note_path == "." or node_path == note_path or node_path.startswith(f"{note_path}/")


def _match_count(query: frozenset[str], tokens: tuple[str, ...]) -> int:
    return len(query.intersection(tokens))


def _has_text_match(evidence: RankEvidence) -> bool:
    return bool(
        evidence.path_matches
        or evidence.symbol_matches
        or evidence.import_matches
        or evidence.docstring_matches
        or evidence.comment_matches
        or evidence.note_match
    )


def _score(evidence: RankEvidence) -> int:
    return (
        evidence.symbol_matches * _SYMBOL_WEIGHT
        + evidence.path_matches * _PATH_WEIGHT
        + evidence.import_matches * _IMPORT_WEIGHT
        + evidence.docstring_matches * _DOCSTRING_WEIGHT
        + evidence.comment_matches * _COMMENT_WEIGHT
        + (_NOTE_WEIGHT if evidence.note_match else 0)
        + min(evidence.connected_nodes, _MAX_CONNECTIVITY_SCORE)
    )


def _candidate_key(candidate: RankedCandidate) -> tuple[int, str, int, str, str, str]:
    kind_order = {"module": 0, "class": 1, "function": 2}
    node = candidate.node
    return (
        -candidate.score,
        node.path,
        kind_order[node.kind],
        node.name,
        node.qualified_name,
        node.id,
    )
