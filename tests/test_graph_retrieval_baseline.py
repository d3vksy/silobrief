from __future__ import annotations

import json
import unittest
from dataclasses import asdict, dataclass
from fractions import Fraction
from pathlib import Path
from typing import ClassVar, Literal, TypeAlias

from silobrief.index import IndexData, build_index, render_index_json
from silobrief.python_structure import extract_structures
from silobrief.ranking import rank_candidates
from silobrief.review import DisclosureChoices, candidate_options, review_selection
from silobrief.sources import snapshot_sources
from silobrief.state import DEFAULT_EXCLUDES, BoundaryData, ConfigData, NotesData

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
CorpusName: TypeAlias = Literal["fixture", "repository"]
ChangeKind: TypeAlias = Literal["add", "modify", "remove"]


@dataclass(frozen=True, order=True, slots=True)
class Target:
    path: str
    qualified_name: str


@dataclass(frozen=True, slots=True)
class BenchmarkTask:
    id: str
    corpus: CorpusName
    change: ChangeKind
    prompt: str
    expected: tuple[Target, ...]
    allowed_support: tuple[Target, ...]
    evidence: str


@dataclass(frozen=True, slots=True)
class TaskResult:
    id: str
    ranked: tuple[Target, ...]
    first_expected_rank: int | None
    expected_found: int
    expected_total: int
    irrelevant_candidates: int
    selected: Target | None
    expanded: tuple[Target, ...]
    context_expected_found: int
    expected_reachable_within_two_hops: int


@dataclass(frozen=True, slots=True)
class BaselineResult:
    repository_source_digest: str
    repository_nodes: int
    repository_edges: int
    fixture_source_digest: str
    fixture_nodes: int
    fixture_edges: int
    tasks: tuple[TaskResult, ...]


def targets(path: str, *qualified_names: str) -> tuple[Target, ...]:
    return tuple(Target(path, name) for name in qualified_names)


TASKS: tuple[BenchmarkTask, ...] = (
    BenchmarkTask(
        "T01-MODIFY",
        "fixture",
        "modify",
        "Update the retry policy so status-code retries apply to HTTP 503 and not HTTP 500. "
        "Keep total=2 and preserve the delivery boundary call order.",
        targets("src/parcel_lab/retry.py", "retry_request"),
        targets("src/parcel_lab/retry.py", "parcel_lab.retry"),
        "validation:v0.2/T01-MODIFY",
    ),
    BenchmarkTask(
        "T02-ADD",
        "fixture",
        "add",
        "Add an optional separator setting to LabelOptions. Existing callers that omit it must "
        "keep current output. Insert it between prefix and reference and preserve uppercase "
        "behavior.",
        targets("src/parcel_lab/labels.py", "LabelOptions", "format_label"),
        targets("src/parcel_lab/labels.py", "parcel_lab.labels"),
        "validation:v0.2/T02-ADD",
    ),
    BenchmarkTask(
        "T03-REMOVE",
        "fixture",
        "remove",
        "Remove the legacy fallback from choose_reference. Accept only primary, return the "
        "stripped value, and raise ValueError when it is blank.",
        targets("src/parcel_lab/cleanup.py", "choose_reference"),
        targets("src/parcel_lab/cleanup.py", "parcel_lab.cleanup"),
        "validation:v0.2/T03-REMOVE",
    ),
    BenchmarkTask(
        "S01-SETUP",
        "repository",
        "add",
        "Initialize a project's deterministic local .silobrief state. Re-running setup over "
        "valid state must not rewrite files, and invalid partial state must be rejected.",
        targets("src/silobrief/state.py", "setup_project"),
        targets("src/silobrief/state.py", "_project_root", "_validate_state"),
        "issue:#5@c1933bf",
    ),
    BenchmarkTask(
        "S02-BOUNDARY",
        "repository",
        "add",
        "Register an excluded project file or directory with a public alias and description. "
        "Reject absolute, parent, outside-project, mixed-separator, and symlink paths.",
        targets("src/silobrief/boundaries.py", "register_boundary"),
        targets("src/silobrief/boundaries.py", "_boundary_path", "_automatic_alias")
        + targets("src/silobrief/state.py", "mark_index_stale"),
        "issue:#7@b7622c8",
    ),
    BenchmarkTask(
        "S03-SOURCES",
        "repository",
        "add",
        "Collect allowed Python sources without opening excluded subtrees or following symlinks, "
        "then calculate a deterministic path-sensitive digest and compare snapshots.",
        targets("src/silobrief/sources.py", "snapshot_sources", "compare_snapshots"),
        targets("src/silobrief/sources.py", "_walk_sources", "_is_excluded", "_snapshot_digest"),
        "issue:#9@40fc7af",
    ),
    BenchmarkTask(
        "S04-AST",
        "repository",
        "add",
        "Extract module, nested class, sync and async function, import, call, and reference "
        "structure from in-memory Python source bytes without retaining source text.",
        targets(
            "src/silobrief/python_structure.py", "extract_structures", "extract_module_structure"
        ),
        targets("src/silobrief/python_structure.py", "PythonParseError", "_StructureVisitor"),
        "issue:#11@75fbbb6",
    ),
    BenchmarkTask(
        "S05-PLACEHOLDER",
        "repository",
        "add",
        "Replace imports, calls, and references into an excluded Python boundary with a "
        "placeholder containing only its public alias and description.",
        targets(
            "src/silobrief/boundary_placeholders.py",
            "BoundaryMatcher",
            "BoundaryMatcher.match_import",
            "BoundaryMatcher.match_use",
        ),
        targets("src/silobrief/boundary_placeholders.py", "BoundaryPlaceholder", "_BoundaryRule"),
        "issue:#15@b4ab6c3",
    ),
    BenchmarkTask(
        "S06-NOTES",
        "repository",
        "add",
        "Record a public human note for an allowed project path. Reject boundaries and symlinks, "
        "preserve note order, and make the ID deterministic.",
        targets("src/silobrief/notes.py", "add_note"),
        targets("src/silobrief/notes.py", "_note_path", "_require_allowed_path", "_note_id"),
        "issue:#17@dbeec78",
    ),
    BenchmarkTask(
        "S07-RANKING",
        "repository",
        "add",
        "Rank no more than ten project nodes for a maintenance prompt using explainable lexical, "
        "note, and graph connectivity evidence.",
        targets("src/silobrief/ranking.py", "rank_candidates"),
        targets("src/silobrief/ranking.py", "RankEvidence", "_evidence", "_score"),
        "issue:#19@18bafc4",
    ),
    BenchmarkTask(
        "S08-REVIEW",
        "repository",
        "add",
        "Review ranked candidates with explicit select, add, exclude choices and expand exactly "
        "one resolved graph hop without traversing boundary placeholders.",
        targets("src/silobrief/review.py", "review_selection"),
        targets("src/silobrief/review.py", "candidate_options", "ReviewSelection", "_expanded_ids"),
        "issue:#21@f389ef3",
    ),
    BenchmarkTask(
        "S09-OUTPUT",
        "repository",
        "add",
        "Preview the complete Markdown and require exact WRITE approval before creating a new "
        "output file. Reject non-TTY, overwrite, symlink, and unsafe paths.",
        targets("src/silobrief/output.py", "approve_and_write"),
        targets("src/silobrief/output.py", "OutputBlockedError", "_output_path", "_write_new_file"),
        "issue:#25@6e1ca1e",
    ),
)

NO_FIELDS = DisclosureChoices(False, False, False, False, False)
EMPTY_NOTES = NotesData(notes=[], notes_version=1)
FORBIDDEN_FIXTURE_VALUES = (
    b"private_adapter",
    b"deliver_internal",
    b"PRIVATE_MODEL_GATE_CANARY",
    b"ignored-adapter-source",
)


def build_corpora(root: Path) -> dict[CorpusName, IndexData]:
    repository_boundaries = (
        BoundaryData(path="examples", alias="benchmark-fixtures", description="Fixture corpus"),
        BoundaryData(path="validation", alias="validation-artifacts", description="Reports"),
        BoundaryData(
            path="tests/test_graph_retrieval_baseline.py",
            alias="benchmark-harness",
            description="Baseline harness",
        ),
        BoundaryData(
            path="tests/test_graph_retrieval_comparison.py",
            alias="comparison-harness",
            description="Comparison harness",
        ),
        BoundaryData(
            path="tests/__init__.py",
            alias="test-package-marker",
            description="Test package marker",
        ),
    )
    fixture_boundaries = (
        BoundaryData(
            path="private_adapter",
            alias="delivery-boundary",
            description="External delivery adapter",
        ),
    )
    return {
        "repository": _build_index(root, repository_boundaries),
        "fixture": _build_index(root / "examples" / "model-validation-fixture", fixture_boundaries),
    }


def run_baseline(indices: dict[CorpusName, IndexData]) -> BaselineResult:
    repository = indices["repository"]
    fixture = indices["fixture"]
    return BaselineResult(
        repository_source_digest=repository.source_digest,
        repository_nodes=len(repository.nodes),
        repository_edges=len(repository.edges),
        fixture_source_digest=fixture.source_digest,
        fixture_nodes=len(fixture.nodes),
        fixture_edges=len(fixture.edges),
        tasks=tuple(_run_task(task, indices[task.corpus]) for task in TASKS),
    )


def canonical_result(result: BaselineResult) -> bytes:
    value: dict[str, object] = {
        "aggregate": _aggregate_value(result),
        "result": asdict(result),
    }
    return (json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n").encode()


def _build_index(root: Path, boundaries: tuple[BoundaryData, ...]) -> IndexData:
    config = ConfigData(
        boundaries=list(boundaries),
        default_excludes=list(DEFAULT_EXCLUDES),
        schema_version=1,
    )
    snapshot = snapshot_sources(root, config)
    return build_index(snapshot, extract_structures(snapshot), config)


def _run_task(task: BenchmarkTask, index: IndexData) -> TaskResult:
    ranked = rank_candidates(task.prompt, index, EMPTY_NOTES)
    ranked_targets = tuple(
        _target(candidate.node.path, candidate.node.qualified_name) for candidate in ranked
    )
    expected = frozenset(task.expected)
    allowed = expected.union(task.allowed_support)
    positions = tuple(
        position
        for position, candidate in enumerate(ranked_targets, start=1)
        if candidate in expected
    )
    selected: Target | None = None
    expanded: tuple[Target, ...] = ()
    if ranked:
        selected_number = positions[0] if positions else 1
        selection = review_selection(
            index,
            candidate_options(ranked),
            selected_numbers=(selected_number,),
            added=(),
            excluded=(),
            fields=NO_FIELDS,
        )
        selected = _target(
            selection.selected[0].path,
            selection.selected[0].qualified_name,
        )
        expanded = tuple(_target(node.path, node.qualified_name) for node in selection.expanded)
    context = frozenset((selected, *expanded)) if selected is not None else frozenset()
    return TaskResult(
        id=task.id,
        ranked=ranked_targets,
        first_expected_rank=positions[0] if positions else None,
        expected_found=len(expected.intersection(ranked_targets)),
        expected_total=len(expected),
        irrelevant_candidates=sum(candidate not in allowed for candidate in ranked_targets),
        selected=selected,
        expanded=expanded,
        context_expected_found=len(expected.intersection(context)),
        expected_reachable_within_two_hops=_reachable_expected(index, ranked_targets, expected),
    )


def _reachable_expected(
    index: IndexData,
    ranked: tuple[Target, ...],
    expected: frozenset[Target],
) -> int:
    ids = {_target(node.path, node.qualified_name): node.id for node in index.nodes}
    adjacency: dict[str, set[str]] = {node.id: set() for node in index.nodes}
    for edge in index.edges:
        if edge.target_id is None or edge.source_id == edge.target_id:
            continue
        adjacency[edge.source_id].add(edge.target_id)
        adjacency[edge.target_id].add(edge.source_id)
    seen = {ids[candidate] for candidate in ranked}
    frontier = set(seen)
    for _ in range(2):
        frontier = {neighbor for node_id in frontier for neighbor in adjacency[node_id]} - seen
        seen.update(frontier)
    return sum(ids[value] in seen for value in expected)


def _target(path: str, qualified_name: str) -> Target:
    return Target(path=path, qualified_name=qualified_name)


def _aggregate_value(result: BaselineResult) -> dict[str, object]:
    reciprocal_rank = sum(
        (
            Fraction(1, task.first_expected_rank)
            for task in result.tasks
            if task.first_expected_rank is not None
        ),
        start=Fraction(),
    )
    return {
        "context_expected_found": sum(task.context_expected_found for task in result.tasks),
        "expanded_nodes": sum(len(task.expanded) for task in result.tasks),
        "expected_found": sum(task.expected_found for task in result.tasks),
        "expected_reachable_within_two_hops": sum(
            task.expected_reachable_within_two_hops for task in result.tasks
        ),
        "expected_total": sum(task.expected_total for task in result.tasks),
        "hits_at_10": sum(task.first_expected_rank is not None for task in result.tasks),
        "irrelevant_candidates": sum(task.irrelevant_candidates for task in result.tasks),
        "maximum_expanded_nodes": max(len(task.expanded) for task in result.tasks),
        "reciprocal_rank_sum": (f"{reciprocal_rank.numerator}/{reciprocal_rank.denominator}"),
        "tasks": len(result.tasks),
    }


class GraphRetrievalBaselineTests(unittest.TestCase):
    indices: ClassVar[dict[CorpusName, IndexData]]
    result: ClassVar[BaselineResult]

    @classmethod
    def setUpClass(cls) -> None:
        cls.indices = build_corpora(REPOSITORY_ROOT)
        cls.result = run_baseline(cls.indices)

    def test_tasks_are_fixed_traceable_and_present_in_their_corpus(self) -> None:
        self.assertEqual(len(TASKS), 12)
        self.assertEqual(len({task.id for task in TASKS}), 12)
        self.assertEqual({task.change for task in TASKS}, {"add", "modify", "remove"})
        for task in TASKS:
            with self.subTest(task=task.id):
                self.assertTrue(task.evidence.startswith(("issue:#", "validation:v0.2/")))
                available = {
                    _target(node.path, node.qualified_name)
                    for node in self.indices[task.corpus].nodes
                }
                self.assertTrue(frozenset(task.expected).issubset(available))
                self.assertTrue(frozenset(task.allowed_support).issubset(available))

    def test_same_inputs_produce_the_same_results(self) -> None:
        repeated = run_baseline(build_corpora(REPOSITORY_ROOT))
        self.assertEqual(self.result, repeated)
        self.assertEqual(canonical_result(self.result), canonical_result(repeated))

    def test_fixture_boundary_values_do_not_reach_index_or_results(self) -> None:
        fixture_json = render_index_json(self.indices["fixture"])
        result_json = canonical_result(self.result)
        for value in FORBIDDEN_FIXTURE_VALUES:
            with self.subTest(value=value):
                self.assertNotIn(value, fixture_json)
                self.assertNotIn(value, result_json)

    def test_v0_7_retrieval_gate(self) -> None:
        tasks = self.result.tasks
        expected_found = sum(task.expected_found for task in tasks)
        expected_total = sum(task.expected_total for task in tasks)
        reciprocal_rank = sum(
            (
                Fraction(1, task.first_expected_rank)
                for task in tasks
                if task.first_expected_rank is not None
            ),
            start=Fraction(),
        )

        self.assertGreaterEqual(sum(task.first_expected_rank is not None for task in tasks), 9)
        self.assertGreaterEqual(Fraction(expected_found, expected_total), Fraction(4, 5))
        self.assertGreaterEqual(reciprocal_rank / len(tasks), Fraction(1, 2))
        self.assertLessEqual(sum(task.irrelevant_candidates for task in tasks), 60)
        self.assertTrue(all(len(task.ranked) <= 10 for task in tasks))


if __name__ == "__main__":
    print(canonical_result(run_baseline(build_corpora(REPOSITORY_ROOT))).decode(), end="")
