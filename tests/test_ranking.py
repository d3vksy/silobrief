from __future__ import annotations

import unittest
from dataclasses import replace

from silobrief.index import IndexData, IndexEdge, IndexNode, NodeKind, NodeTokens
from silobrief.ranking import RankedCandidate, RankEvidence, rank_candidates
from silobrief.state import HumanNoteData, NotesData


def node(
    node_id: str,
    path: str,
    kind: NodeKind,
    name: str,
    *,
    path_tokens: tuple[str, ...] = (),
    symbol_tokens: tuple[str, ...] = (),
    import_tokens: tuple[str, ...] = (),
    comment_tokens: tuple[str, ...] = (),
    docstring_tokens: tuple[str, ...] = (),
) -> IndexNode:
    return IndexNode(
        id=node_id,
        kind=kind,
        name=name,
        qualified_name=name,
        path=path,
        tokens=NodeTokens(
            path=path_tokens,
            symbol=symbol_tokens,
            imports=import_tokens,
            comments=comment_tokens,
            docstrings=docstring_tokens,
        ),
    )


def index(
    *nodes: IndexNode,
    edges: tuple[IndexEdge, ...] = (),
) -> IndexData:
    return IndexData(
        config_digest="a" * 64,
        edges=edges,
        index_version=1,
        nodes=nodes,
        source_digest="b" * 64,
        stale=False,
    )


def notes(*items: HumanNoteData) -> NotesData:
    return NotesData(notes=list(items), notes_version=1)


class LexicalRankingTests(unittest.TestCase):
    def test_scores_each_explainable_component_and_caps_connectivity(self) -> None:
        candidate = node(
            "candidate",
            "package/service.py",
            "function",
            "RetryClient",
            path_tokens=("package", "retry", "service"),
            symbol_tokens=("client", "retry"),
            import_tokens=("http",),
            comment_tokens=("comment",),
            docstring_tokens=("docs",),
        )
        neighbors = tuple(
            node(f"neighbor-{number}", f"other/{number}.py", "function", f"neighbor{number}")
            for number in range(4)
        )
        edges = (
            IndexEdge("candidate", "call", "one", "neighbor-0"),
            IndexEdge("candidate", "reference", "one", "neighbor-0"),
            IndexEdge("candidate", "call", "two", "neighbor-1"),
            IndexEdge("neighbor-2", "call", "candidate", "candidate"),
            IndexEdge("neighbor-3", "reference", "candidate", "candidate"),
            IndexEdge("candidate", "import", "external", None),
        )
        human_notes = notes(
            HumanNoteData(
                id=f"note-{'a' * 64}",
                path="package/service.py",
                comment="NOTE maintenance context",
            )
        )

        source_index = index(candidate, *neighbors, edges=edges)
        ranked = rank_candidates(
            "RetryClient retry HTTP docs comment note",
            source_index,
            human_notes,
        )
        reordered = rank_candidates(
            "RetryClient retry HTTP docs comment note",
            replace(
                source_index,
                edges=tuple(reversed(source_index.edges)),
                nodes=tuple(reversed(source_index.nodes)),
            ),
            human_notes,
        )

        self.assertEqual(ranked, reordered)
        self.assertEqual(
            ranked,
            (
                RankedCandidate(
                    node=candidate,
                    score=27,
                    evidence=RankEvidence(
                        path_matches=("retry",),
                        symbol_matches=("client", "retry"),
                        import_matches=("http",),
                        docstring_matches=("docs",),
                        comment_matches=("comment",),
                        note_matches=("note",),
                        connected_nodes=4,
                    ),
                ),
            ),
        )

    def test_directory_and_file_notes_apply_only_to_matching_nodes(self) -> None:
        service = node("service", "package/service.py", "function", "service")
        worker = node("worker", "package/jobs/worker.py", "function", "worker")
        unrelated = node("other", "other.py", "function", "other")
        human_notes = notes(
            HumanNoteData(
                id=f"note-{'a' * 64}",
                path="package",
                comment="Retry ownership",
            ),
            HumanNoteData(
                id=f"note-{'b' * 64}",
                path="other.py",
                comment="Different context",
            ),
        )

        ranked = rank_candidates("retry", index(unrelated, worker, service), human_notes)
        reversed_notes = notes(*reversed(human_notes["notes"]))
        reordered = rank_candidates(
            "retry",
            index(service, worker, unrelated),
            reversed_notes,
        )

        self.assertEqual(ranked, reordered)
        self.assertEqual([item.node.id for item in ranked], ["worker", "service"])
        self.assertTrue(all(item.score == 4 for item in ranked))
        self.assertTrue(all(item.evidence.note_matches == ("retry",) for item in ranked))

    def test_limits_results_and_uses_deterministic_tie_breakers(self) -> None:
        same_path = (
            node("module", "a.py", "module", "module", symbol_tokens=("match",)),
            node("class", "a.py", "class", "class", symbol_tokens=("match",)),
            node("function-a", "a.py", "function", "alpha", symbol_tokens=("match",)),
            node("function-b", "a.py", "function", "beta", symbol_tokens=("match",)),
        )
        remaining = tuple(
            node(
                f"node-{number:02}",
                f"path-{number:02}.py",
                "function",
                f"name-{number:02}",
                symbol_tokens=("match",),
            )
            for number in range(9)
        )
        source_index = index(*same_path, *remaining)

        ranked = rank_candidates("match", source_index, notes())
        reordered = rank_candidates(
            "match",
            replace(source_index, nodes=tuple(reversed(source_index.nodes))),
            notes(),
        )

        self.assertEqual(ranked, reordered)
        self.assertEqual(len(ranked), 10)
        self.assertEqual(
            [item.node.id for item in ranked[:4]],
            ["module", "class", "function-a", "function-b"],
        )
        self.assertTrue(all(item.score == 5 for item in ranked))

    def test_requires_literal_token_overlap_without_translation(self) -> None:
        retry = node(
            "retry",
            "service.py",
            "function",
            "RetryRequest",
            symbol_tokens=("request", "retry"),
        )

        self.assertEqual(rank_candidates("재시도", index(retry), notes()), ())
        self.assertEqual(rank_candidates("---", index(retry), notes()), ())
        self.assertEqual(rank_candidates("RetryRequest", index(retry), notes())[0].score, 10)


if __name__ == "__main__":
    unittest.main()
