from __future__ import annotations

import hashlib
import unittest
from typing import ClassVar

from tests.test_graph_retrieval_baseline import (
    FORBIDDEN_FIXTURE_VALUES,
    REPOSITORY_ROOT,
    build_corpora,
    canonical_result,
    run_baseline,
)
from validation.graph_retrieval_comparison import (
    STRATEGY_NAMES,
    ComparisonResult,
    canonical_comparison,
    run_comparison,
)

BASELINE_SHA256 = "4c3bd3590b44ae517552f44d2a66f5d33522354d17cea2c9205f070ae19e5bc2"


class GraphRetrievalComparisonTests(unittest.TestCase):
    result: ClassVar[ComparisonResult]

    @classmethod
    def setUpClass(cls) -> None:
        cls.result = run_comparison(build_corpora(REPOSITORY_ROOT))

    def test_baseline_fingerprint_is_unchanged(self) -> None:
        baseline = canonical_result(run_baseline(build_corpora(REPOSITORY_ROOT)))
        self.assertEqual(hashlib.sha256(baseline).hexdigest(), BASELINE_SHA256)

    def test_comparison_is_deterministic(self) -> None:
        repeated = run_comparison(build_corpora(REPOSITORY_ROOT))
        self.assertEqual(self.result, repeated)
        self.assertEqual(canonical_comparison(self.result), canonical_comparison(repeated))

    def test_strategies_follow_fixed_bounds(self) -> None:
        self.assertEqual(tuple(item.name for item in self.result.strategies), STRATEGY_NAMES)
        for strategy in self.result.strategies:
            self.assertEqual(len(strategy.tasks), 12)
            for task in strategy.tasks:
                with self.subTest(strategy=strategy.name, task=task.id):
                    self.assertLessEqual(len(task.ranked), 10)
                    self.assertLessEqual(len(task.expanded), 10)

    def test_source_first_keeps_the_fixed_repository_split(self) -> None:
        source_first = self.result.strategies[0]
        for task in source_first.tasks[3:]:
            with self.subTest(task=task.id):
                self.assertTrue(all(node.path.startswith("src/") for node in task.ranked[:7]))
                self.assertTrue(all(not node.path.startswith("src/") for node in task.ranked[7:]))

    def test_gate_decision_lists_every_failed_criterion(self) -> None:
        for strategy in self.result.strategies:
            with self.subTest(strategy=strategy.name):
                self.assertEqual(strategy.gate_passed, not strategy.failed_criteria)

    def test_fixture_boundary_values_do_not_reach_results(self) -> None:
        encoded = canonical_comparison(self.result)
        for value in FORBIDDEN_FIXTURE_VALUES:
            with self.subTest(value=value):
                self.assertNotIn(value, encoded)


if __name__ == "__main__":
    print(canonical_comparison(run_comparison(build_corpora(REPOSITORY_ROOT))).decode(), end="")
