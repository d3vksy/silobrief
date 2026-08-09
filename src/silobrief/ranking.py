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
    path_matches: tuple[str, ...]
    symbol_matches: tuple[str, ...]
    import_matches: tuple[str, ...]
    docstring_matches: tuple[str, ...]
    comment_matches: tuple[str, ...]
    note_matches: tuple[str, ...]
    connected_nodes: int

    @property
    def note_match(self) -> bool:
        return bool(self.note_matches)


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
        path_matches=_matches(query, node.tokens.path),
        symbol_matches=_matches(query, node.tokens.symbol),
        import_matches=_matches(query, node.tokens.imports),
        docstring_matches=_matches(query, node.tokens.docstrings),
        comment_matches=_matches(query, node.tokens.comments),
        note_matches=tuple(
            sorted(
                {
                    token
                    for note, tokens in note_tokens
                    if _note_applies(note["path"], node.path)
                    for token in query.intersection(tokens)
                }
            )
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


def _matches(query: frozenset[str], tokens: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(sorted(query.intersection(tokens)))


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
        len(evidence.symbol_matches) * _SYMBOL_WEIGHT
        + len(evidence.path_matches) * _PATH_WEIGHT
        + len(evidence.import_matches) * _IMPORT_WEIGHT
        + len(evidence.docstring_matches) * _DOCSTRING_WEIGHT
        + len(evidence.comment_matches) * _COMMENT_WEIGHT
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
