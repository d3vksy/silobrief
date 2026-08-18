from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import PurePosixPath

from silobrief.index import IndexData, IndexNode
from silobrief.search_tokens import normalize_search_tokens
from silobrief.state import HumanNoteData, NotesData

_SYMBOL_WEIGHT = 5
_PATH_WEIGHT = 4
_DOCSTRING_WEIGHT = 2
_COMMENT_WEIGHT = 1
_NOTE_WEIGHT = 4
_IMPORT_TIE_BREAK_CAP = 2
_MAX_CONNECTIVITY_SCORE = 3
_MAX_CANDIDATES = 10
_MAX_IMPLEMENTATION_CANDIDATES = 7
_MAX_TEST_CANDIDATES = _MAX_CANDIDATES - _MAX_IMPLEMENTATION_CANDIDATES
_LEADING_ACTION_BONUS = 8
_EXACT_MODULE_BONUS = 4
_TEST_QUERY_TOKENS = frozenset({"test", "tests", "pytest", "unittest", "테스트"})
_WORD_PATTERN = re.compile(r"[^\W_]+", re.UNICODE)


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
    query = _query_tokens(prompt)
    if not query:
        return ()
    first_word = _first_query_word(prompt)

    adjacency = _adjacency(index)
    note_tokens = tuple(
        (note, frozenset(normalize_search_tokens(note["comment"]))) for note in notes["notes"]
    )
    candidates: list[RankedCandidate] = []
    module_fallbacks: list[RankedCandidate] = []
    for candidate in index.nodes:
        evidence = _evidence(candidate, query, adjacency, note_tokens)
        if not _has_direct_match(evidence):
            continue
        ranked = RankedCandidate(
            node=candidate,
            score=_score(candidate, evidence, query=query, first_word=first_word),
            evidence=evidence,
        )
        (module_fallbacks if candidate.kind == "module" else candidates).append(ranked)
    candidates.sort(key=_candidate_key)
    module_fallbacks.sort(key=_candidate_key)
    if not candidates:
        candidates = module_fallbacks
    return _bounded_candidates(candidates, include_tests=bool(query & _TEST_QUERY_TOKENS))


def _query_tokens(prompt: str) -> frozenset[str]:
    tokens = set(normalize_search_tokens(prompt))
    for token in tuple(tokens):
        if len(token) > 4 and token.endswith("ies"):
            tokens.add(f"{token[:-3]}y")
        elif len(token) > 4 and token.endswith("s") and not token.endswith(("ss", "us", "is")):
            tokens.add(token[:-1])
        if len(token) > 5 and token.endswith("ing"):
            tokens.add(token[:-3])
    return frozenset(tokens)


def _first_query_word(prompt: str) -> str:
    match = _WORD_PATTERN.search(prompt)
    return match.group(0).casefold() if match is not None else ""


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


def _has_direct_match(evidence: RankEvidence) -> bool:
    return bool(
        evidence.path_matches
        or evidence.symbol_matches
        or evidence.docstring_matches
        or evidence.comment_matches
        or evidence.note_match
    )


def _score(
    node: IndexNode,
    evidence: RankEvidence,
    *,
    query: frozenset[str],
    first_word: str,
) -> int:
    score = (
        len(evidence.symbol_matches) * _SYMBOL_WEIGHT
        + len(evidence.path_matches) * _PATH_WEIGHT
        + min(len(evidence.import_matches), _IMPORT_TIE_BREAK_CAP)
        + len(evidence.docstring_matches) * _DOCSTRING_WEIGHT
        + len(evidence.comment_matches) * _COMMENT_WEIGHT
        + (_NOTE_WEIGHT if evidence.note_match else 0)
        + min(evidence.connected_nodes, _MAX_CONNECTIVITY_SCORE)
    )
    if node.kind == "function" and first_word and node.name.casefold().startswith(first_word):
        score += _LEADING_ACTION_BONUS
    if PurePosixPath(node.path).stem.casefold() in query:
        score += _EXACT_MODULE_BONUS
    return score


def _bounded_candidates(
    candidates: list[RankedCandidate], *, include_tests: bool
) -> tuple[RankedCandidate, ...]:
    implementation = [
        candidate for candidate in candidates if not _is_test_path(candidate.node.path)
    ]
    if not include_tests:
        return tuple(implementation[:_MAX_IMPLEMENTATION_CANDIDATES])

    tests = [candidate for candidate in candidates if _is_test_path(candidate.node.path)]
    selected = [
        *implementation[:_MAX_IMPLEMENTATION_CANDIDATES],
        *tests[:_MAX_TEST_CANDIDATES],
    ]
    if len(implementation) < _MAX_IMPLEMENTATION_CANDIDATES:
        selected = [
            *implementation,
            *tests[: _MAX_CANDIDATES - len(implementation)],
        ]
    elif len(tests) < _MAX_TEST_CANDIDATES:
        selected = [
            *implementation[: _MAX_CANDIDATES - len(tests)],
            *tests,
        ]
    return tuple(selected)


def _is_test_path(path: str) -> bool:
    parts = PurePosixPath(path).parts
    filename = parts[-1]
    return (
        "test" in parts
        or "tests" in parts
        or filename.startswith("test_")
        or filename.endswith("_test.py")
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
