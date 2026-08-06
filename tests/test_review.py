from __future__ import annotations

import unittest
from dataclasses import asdict, replace
from unittest import mock

from silobrief.index import IndexData, IndexEdge, IndexNode, NodeKind, NodeTokens
from silobrief.ranking import RankedCandidate, RankEvidence
from silobrief.review import (
    CandidateOption,
    DisclosureChoices,
    ReviewError,
    ReviewNode,
    candidate_options,
    review_selection,
    selector_symbol_options,
)


def node(
    node_id: str,
    path: str,
    kind: NodeKind,
    name: str,
    qualified_name: str | None = None,
) -> IndexNode:
    return IndexNode(
        id=node_id,
        kind=kind,
        name=name,
        qualified_name=qualified_name or name,
        path=path,
        tokens=NodeTokens(
            path=("raw-canary",),
            symbol=("raw-canary",),
            imports=("raw-canary",),
            comments=("raw-canary",),
            docstrings=("raw-canary",),
        ),
    )


def index(*nodes: IndexNode, edges: tuple[IndexEdge, ...] = ()) -> IndexData:
    return IndexData(
        config_digest="a" * 64,
        edges=edges,
        index_version=1,
        nodes=nodes,
        source_digest="b" * 64,
        stale=False,
    )


def ranked(candidate: IndexNode, score: int) -> RankedCandidate:
    return RankedCandidate(
        node=candidate,
        score=score,
        evidence=RankEvidence(
            path_matches=1,
            symbol_matches=0,
            import_matches=0,
            docstring_matches=0,
            comment_matches=0,
            note_match=False,
            connected_nodes=0,
        ),
    )


FIELDS = DisclosureChoices(
    paths=True,
    symbols=True,
    public_libraries=False,
    human_notes=True,
    boundary_placeholders=False,
)


class CandidateOptionTests(unittest.TestCase):
    def test_builds_deterministic_safe_options_without_search_tokens(self) -> None:
        alpha = node("alpha", "a.py", "function", "alpha")
        beta = node("beta", "b.py", "class", "beta")
        source = (ranked(beta, 4), ranked(alpha, 8))

        options = candidate_options(source)
        reordered = candidate_options(tuple(reversed(source)))

        self.assertEqual(options, reordered)
        self.assertEqual([option.number for option in options], [1, 2])
        self.assertEqual([option.node.id for option in options], ["alpha", "beta"])
        self.assertEqual(options[0].score, 8)
        self.assertEqual(options[0].evidence, source[1].evidence)
        self.assertFalse(hasattr(options[0].node, "tokens"))
        self.assertNotIn("raw-canary", repr(tuple(asdict(option) for option in options)))


class SelectorSymbolOptionTests(unittest.TestCase):
    def test_lists_indexed_symbols_in_a_deterministic_safe_order(self) -> None:
        module = node("module", "src/service.py", "module", "service")
        service = node("service", "src/service.py", "class", "Service")
        method = node("method", "src/service.py", "function", "run", "Service.run")
        helper = node("helper", "src/service.py", "function", "helper")
        other = node("other", "src/other.py", "function", "other")
        source = index(other, helper, method, module, service)

        blocked = AssertionError("outline must use the current index only")
        with (
            mock.patch("builtins.open", side_effect=blocked),
            mock.patch("pathlib.Path.open", side_effect=blocked),
            mock.patch("pathlib.Path.iterdir", side_effect=blocked),
            mock.patch("os.scandir", side_effect=blocked),
            mock.patch("ast.parse", side_effect=blocked),
        ):
            options = selector_symbol_options(source, "src/service.py")
        reordered = selector_symbol_options(
            replace(source, nodes=tuple(reversed(source.nodes))), "src/service.py"
        )

        self.assertEqual(options, reordered)
        self.assertEqual([option.number for option in options or ()], [1, 2, 3])
        self.assertEqual(
            [option.node.id for option in options or ()],
            ["service", "method", "helper"],
        )
        self.assertNotIn("raw-canary", repr(options))
        self.assertIsNone(selector_symbol_options(source, "service"))

    def test_returns_an_empty_outline_and_rejects_unknown_selectors(self) -> None:
        module = node("module", "src/empty.py", "module", "empty")
        source = index(module)

        self.assertEqual(selector_symbol_options(source, "src/empty.py"), ())
        for selector in (
            "src/missing.py",
            "../secret.py",
            "/src/empty.py",
            "C:/project/src/empty.py",
            "src\\empty.py",
            "src\\nested/empty.py",
            "src",
        ):
            with self.subTest(selector=selector):
                with self.assertRaisesRegex(ReviewError, "not present in the current index"):
                    selector_symbol_options(source, selector)


class ReviewSelectionTests(unittest.TestCase):
    def test_selects_adds_excludes_and_expands_exactly_one_step(self) -> None:
        root = node("root", "src/a.py", "function", "root")
        added_module = node("added-module", "src/added.py", "module", "added")
        added_function = node("added-function", "src/added.py", "function", "work")
        neighbor = node("neighbor", "src/b.py", "class", "neighbor")
        second_hop = node("second", "src/c.py", "function", "second")
        excluded = node("excluded", "src/excluded.py", "module", "excluded")
        edges = (
            IndexEdge("root", "call", "neighbor", "neighbor"),
            IndexEdge("neighbor", "reference", "second", "second"),
            IndexEdge("root", "contains", "excluded", "excluded"),
            IndexEdge("root", "import", "external", None),
            IndexEdge("root", "call", "root", "root"),
        )
        source_index = index(
            second_hop,
            excluded,
            neighbor,
            added_function,
            added_module,
            root,
            edges=edges,
        )
        options = candidate_options((ranked(root, 5),))

        result = review_selection(
            source_index,
            options,
            selected_numbers=(1, 1),
            added=("src/added.py", "added-module"),
            excluded=("src/excluded.py",),
            fields=FIELDS,
        )
        reordered = review_selection(
            replace(
                source_index,
                edges=tuple(reversed(source_index.edges)),
                nodes=tuple(reversed(source_index.nodes)),
            ),
            tuple(reversed(options)),
            selected_numbers=(1,),
            added=("added-module", "src/added.py"),
            excluded=("src/excluded.py", "src/excluded.py"),
            fields=FIELDS,
        )

        self.assertEqual(result, reordered)
        self.assertEqual([item.id for item in result.selected], ["root", "added-module"])
        self.assertEqual(
            result.expanded, (ReviewNode("neighbor", "src/b.py", "class", "neighbor", "neighbor"),)
        )
        self.assertEqual(result.fields, FIELDS)
        self.assertNotIn("raw-canary", repr(asdict(result)))

    def test_direct_node_addition_is_an_explicit_start_selection(self) -> None:
        suggested = node("suggested", "suggested.py", "module", "suggested")
        direct = node("direct", "direct.py", "function", "direct")
        options = candidate_options((ranked(suggested, 4),))

        result = review_selection(
            index(suggested, direct),
            options,
            selected_numbers=(),
            added=("direct",),
            excluded=(),
            fields=FIELDS,
        )

        self.assertEqual([item.id for item in result.selected], ["direct"])

    def test_allows_direct_selection_when_ranked_candidates_are_empty(self) -> None:
        module = node("module", "src/work.py", "module", "work")
        function = node("function", "src/work.py", "function", "run")

        result = review_selection(
            index(function, module),
            (),
            selected_numbers=(),
            added=("src/work.py", "function"),
            excluded=(),
            fields=FIELDS,
        )

        self.assertEqual([item.id for item in result.selected], ["module", "function"])

        by_node_id = review_selection(
            index(function, module),
            (),
            selected_numbers=(),
            added=("module", "function"),
            excluded=(),
            fields=FIELDS,
        )
        self.assertEqual(result, by_node_id)

    def test_rejects_missing_candidates_selections_and_unknown_references(self) -> None:
        root = node("root", "root.py", "module", "root")
        options = candidate_options((ranked(root, 4),))
        source_index = index(root)

        cases = (
            ((), (), (), (), "start selection"),
            ((), (1,), (), (), "candidate number"),
            (options, (2,), (), (), "candidate number"),
            (options, (), ("missing.py",), (), "selector"),
            (options, (1,), (), ("missing",), "selector"),
            (options, (1,), (), ("root",), "start selection"),
        )
        for supplied_options, selected, added, excluded, message in cases:
            with self.subTest(message=message):
                with self.assertRaisesRegex(ReviewError, message):
                    review_selection(
                        source_index,
                        supplied_options,
                        selected_numbers=selected,
                        added=added,
                        excluded=excluded,
                        fields=FIELDS,
                    )

    def test_rejects_candidate_from_another_index(self) -> None:
        root = node("root", "root.py", "module", "root")
        foreign = node("foreign", "foreign.py", "module", "foreign")
        option = CandidateOption(
            number=1,
            node=ReviewNode("foreign", "foreign.py", "module", "foreign", "foreign"),
            score=4,
            evidence=ranked(foreign, 4).evidence,
        )

        with self.assertRaisesRegex(ReviewError, "current index"):
            review_selection(
                index(root),
                (option,),
                selected_numbers=(1,),
                added=(),
                excluded=(),
                fields=FIELDS,
            )


if __name__ == "__main__":
    unittest.main()
