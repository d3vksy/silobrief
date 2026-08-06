from __future__ import annotations

import heapq
import json
from collections.abc import Callable
from dataclasses import asdict, dataclass
from fractions import Fraction
from pathlib import PurePosixPath
from typing import Literal, TypeAlias

from silobrief.index import EdgeKind, IndexData, IndexNode
from silobrief.ranking import RankedCandidate, rank_candidates
from tests.test_graph_retrieval_baseline import (
    EMPTY_NOTES,
    FORBIDDEN_FIXTURE_VALUES,
    TASKS,
    BenchmarkTask,
    CorpusName,
    Target,
)

StrategyName: TypeAlias = Literal["source-first", "bounded-graph"]
STRATEGY_NAMES: tuple[StrategyName, ...] = ("source-first", "bounded-graph")
_SOURCE_QUOTA = 7
_OTHER_QUOTA = 3
_MAX_CANDIDATES = 10
_MAX_EXPANDED = 10
_MAX_GRAPH_HOPS = 2
_RELATION_ORDER = {"import": 0, "call": 1, "reference": 2, "contains": 3}
_KIND_ORDER = {"module": 0, "class": 1, "function": 2}


@dataclass(frozen=True, slots=True)
class ComparisonTaskResult:
    id: str
    ranked: tuple[Target, ...]
    first_expected_rank: int | None
    expected_found: int
    expected_total: int
    irrelevant_candidates: int
    selected: Target | None
    expanded: tuple[Target, ...]
    context_expected_found: int


@dataclass(frozen=True, slots=True)
class StrategyAggregate:
    fixture_hits_at_10: int
    fixture_tasks: int
    fixture_expected_found: int
    fixture_expected_total: int
    hits_at_10: int
    tasks: int
    expected_found: int
    expected_total: int
    context_expected_found: int
    mean_reciprocal_rank: str
    irrelevant_candidates: int
    expanded_nodes: int
    maximum_expanded_nodes: int
    boundary_leaks: int


@dataclass(frozen=True, slots=True)
class StrategyResult:
    name: StrategyName
    aggregate: StrategyAggregate
    tasks: tuple[ComparisonTaskResult, ...]
    gate_passed: bool
    failed_criteria: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ComparisonResult:
    repository_source_digest: str
    fixture_source_digest: str
    strategies: tuple[StrategyResult, ...]


def run_comparison(indices: dict[CorpusName, IndexData]) -> ComparisonResult:
    return ComparisonResult(
        repository_source_digest=indices["repository"].source_digest,
        fixture_source_digest=indices["fixture"].source_digest,
        strategies=tuple(_run_strategy(name, indices) for name in STRATEGY_NAMES),
    )


def canonical_comparison(result: ComparisonResult) -> bytes:
    return (json.dumps(asdict(result), ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")


def _run_strategy(
    name: StrategyName,
    indices: dict[CorpusName, IndexData],
) -> StrategyResult:
    tasks = tuple(_run_task(name, task, indices[task.corpus]) for task in TASKS)
    aggregate = _aggregate(tasks)
    failed = _failed_criteria(aggregate)
    return StrategyResult(name, aggregate, tasks, not failed, failed)


def _run_task(
    strategy: StrategyName,
    task: BenchmarkTask,
    index: IndexData,
) -> ComparisonTaskResult:
    source_first = _source_first_candidates(task.prompt, index)
    nodes = (
        tuple(candidate.node for candidate in source_first)
        if strategy == "source-first"
        else _bounded_graph_candidates(index, source_first)
    )
    ranked = tuple(_target(node) for node in nodes)
    expected = frozenset(task.expected)
    allowed = expected.union(task.allowed_support)
    positions = tuple(
        position for position, candidate in enumerate(ranked, start=1) if candidate in expected
    )
    selected_node = nodes[positions[0] - 1 if positions else 0] if nodes else None
    expanded_nodes = (
        ()
        if selected_node is None
        else _expand_selected(index, selected_node, strategy == "bounded-graph")
    )
    selected = _target(selected_node) if selected_node is not None else None
    expanded = tuple(_target(node) for node in expanded_nodes)
    context = frozenset((selected, *expanded)) if selected is not None else frozenset()
    return ComparisonTaskResult(
        id=task.id,
        ranked=ranked,
        first_expected_rank=positions[0] if positions else None,
        expected_found=len(expected.intersection(ranked)),
        expected_total=len(expected),
        irrelevant_candidates=sum(candidate not in allowed for candidate in ranked),
        selected=selected,
        expanded=expanded,
        context_expected_found=len(expected.intersection(context)),
    )


def _source_first_candidates(prompt: str, index: IndexData) -> tuple[RankedCandidate, ...]:
    source = rank_candidates(prompt, _subset(index, _is_source_node), EMPTY_NOTES)
    other = rank_candidates(
        prompt, _subset(index, lambda node: not _is_source_node(node)), EMPTY_NOTES
    )
    result = [*source[:_SOURCE_QUOTA], *other[:_OTHER_QUOTA]]
    if len(source) < _SOURCE_QUOTA:
        missing = _SOURCE_QUOTA - len(source)
        result.extend(other[_OTHER_QUOTA : _OTHER_QUOTA + missing])
    if len(other) < _OTHER_QUOTA:
        missing = _OTHER_QUOTA - len(other)
        result.extend(source[_SOURCE_QUOTA : _SOURCE_QUOTA + missing])
    return tuple(result[:_MAX_CANDIDATES])


def _bounded_graph_candidates(
    index: IndexData,
    source_first: tuple[RankedCandidate, ...],
) -> tuple[IndexNode, ...]:
    seeds = tuple(candidate.node for candidate in source_first)
    chosen = [node for node in seeds if _is_source_node(node)][:_SOURCE_QUOTA]
    seen = {node.id for node in chosen}
    for node in _graph_discoveries(index, seeds, _is_source_node):
        if node.id not in seen:
            chosen.append(node)
            seen.add(node.id)
        if len(chosen) == _MAX_CANDIDATES:
            return tuple(chosen)
    for node in seeds:
        if node.id not in seen:
            chosen.append(node)
            seen.add(node.id)
        if len(chosen) == _MAX_CANDIDATES:
            break
    return tuple(chosen)


def _expand_selected(
    index: IndexData,
    selected: IndexNode,
    graph_enabled: bool,
) -> tuple[IndexNode, ...]:
    if graph_enabled:
        return _graph_discoveries(index, (selected,), lambda node: True)
    nodes = {node.id: node for node in index.nodes}
    neighbors: set[str] = set()
    for edge in index.edges:
        if edge.target_id is None or edge.source_id == edge.target_id:
            continue
        if edge.source_id == selected.id:
            neighbors.add(edge.target_id)
        if edge.target_id == selected.id:
            neighbors.add(edge.source_id)
    return tuple(sorted((nodes[node_id] for node_id in neighbors), key=_node_key))[:_MAX_EXPANDED]


def _graph_discoveries(
    index: IndexData,
    seeds: tuple[IndexNode, ...],
    include: Callable[[IndexNode], bool],
) -> tuple[IndexNode, ...]:
    nodes = {node.id: node for node in index.nodes}
    adjacency, parents = _normalized_graph(index, nodes)
    contexts = tuple(_owner_contexts(seed.id, parents) for seed in seeds)
    excluded = {node_id for values in contexts for node_id in values}
    best: dict[str, tuple[int, tuple[int, ...], int, tuple[str, int, str, str]]] = {}
    for seed_rank, starts in enumerate(contexts, start=1):
        queue: list[tuple[int, tuple[int, ...], tuple[str, int, str, str], str]] = []
        visited: dict[str, tuple[int, tuple[int, ...]]] = {}
        for node_id in starts:
            heapq.heappush(queue, (0, (), _node_key(nodes[node_id]), node_id))
            visited[node_id] = (0, ())
        while queue:
            distance, relations, _, node_id = heapq.heappop(queue)
            if distance == _MAX_GRAPH_HOPS:
                continue
            for neighbor_id, kind in adjacency[node_id]:
                next_distance = distance + 1
                next_relations = (*relations, _RELATION_ORDER[kind])
                visit_key = (next_distance, next_relations)
                if visit_key >= visited.get(neighbor_id, (_MAX_GRAPH_HOPS + 1, ())):
                    continue
                visited[neighbor_id] = visit_key
                heapq.heappush(
                    queue,
                    (next_distance, next_relations, _node_key(nodes[neighbor_id]), neighbor_id),
                )
                if neighbor_id in excluded or not include(nodes[neighbor_id]):
                    continue
                candidate_key = (
                    next_distance,
                    next_relations,
                    seed_rank,
                    _node_key(nodes[neighbor_id]),
                )
                if candidate_key < best.get(
                    neighbor_id,
                    (_MAX_GRAPH_HOPS + 1, (), len(seeds) + 1, _node_key(nodes[neighbor_id])),
                ):
                    best[neighbor_id] = candidate_key
    ordered = sorted(best, key=lambda node_id: best[node_id])
    return tuple(nodes[node_id] for node_id in ordered[:_MAX_EXPANDED])


def _normalized_graph(
    index: IndexData,
    nodes: dict[str, IndexNode],
) -> tuple[dict[str, tuple[tuple[str, EdgeKind], ...]], dict[str, str]]:
    aliases = _source_aliases(index.nodes)
    neighbors: dict[str, set[tuple[str, EdgeKind]]] = {node_id: set() for node_id in nodes}
    parents: dict[str, str] = {}
    for edge in index.edges:
        target_id = edge.target_id
        if target_id is None and edge.kind == "import" and isinstance(edge.target, str):
            target = _absolute_import_target(edge.source_id, edge.target, nodes)
            target_id = aliases.get(target) if target is not None else None
        if target_id not in nodes or edge.source_id not in nodes or edge.source_id == target_id:
            continue
        neighbors[edge.source_id].add((target_id, edge.kind))
        neighbors[target_id].add((edge.source_id, edge.kind))
        if edge.kind == "contains":
            parents[target_id] = edge.source_id
    return (
        {
            node_id: tuple(
                sorted(
                    values, key=lambda item: (_RELATION_ORDER[item[1]], _node_key(nodes[item[0]]))
                )
            )
            for node_id, values in neighbors.items()
        },
        parents,
    )


def _source_aliases(nodes: tuple[IndexNode, ...]) -> dict[str, str]:
    candidates: dict[str, set[str]] = {}
    for node in nodes:
        module = _source_module(node.path)
        if module is None:
            continue
        alias = module if node.kind == "module" else f"{module}.{node.qualified_name}"
        candidates.setdefault(alias, set()).add(node.id)
    return {alias: next(iter(ids)) for alias, ids in candidates.items() if len(ids) == 1}


def _absolute_import_target(
    source_id: str,
    target: str,
    nodes: dict[str, IndexNode],
) -> str | None:
    if not target.startswith("."):
        return target
    source = nodes[source_id]
    module = _source_module(source.path)
    if module is None:
        return None
    package = module.split(".") if source.path.endswith("/__init__.py") else module.split(".")[:-1]
    level = len(target) - len(target.lstrip("."))
    upward = level - 1
    if upward > len(package):
        return None
    if upward:
        package = package[:-upward]
    suffix = target[level:]
    return ".".join((*package, *suffix.split("."))) if suffix else ".".join(package)


def _owner_contexts(node_id: str, parents: dict[str, str]) -> tuple[str, ...]:
    result = [node_id]
    while result[-1] in parents:
        result.append(parents[result[-1]])
    return tuple(result)


def _subset(index: IndexData, include: Callable[[IndexNode], bool]) -> IndexData:
    nodes = tuple(node for node in index.nodes if include(node))
    node_ids = {node.id for node in nodes}
    edges = tuple(
        edge for edge in index.edges if edge.source_id in node_ids and edge.target_id in node_ids
    )
    return IndexData(
        config_digest=index.config_digest,
        edges=edges,
        index_version=index.index_version,
        nodes=nodes,
        source_digest=index.source_digest,
        stale=index.stale,
    )


def _aggregate(tasks: tuple[ComparisonTaskResult, ...]) -> StrategyAggregate:
    fixture = tasks[:3]
    reciprocal_rank = sum(
        (
            Fraction(1, task.first_expected_rank)
            for task in tasks
            if task.first_expected_rank is not None
        ),
        start=Fraction(),
    ) / len(tasks)
    encoded = json.dumps(
        [asdict(task) for task in tasks], ensure_ascii=False, sort_keys=True
    ).encode("utf-8")
    return StrategyAggregate(
        fixture_hits_at_10=sum(task.first_expected_rank is not None for task in fixture),
        fixture_tasks=len(fixture),
        fixture_expected_found=sum(task.expected_found for task in fixture),
        fixture_expected_total=sum(task.expected_total for task in fixture),
        hits_at_10=sum(task.first_expected_rank is not None for task in tasks),
        tasks=len(tasks),
        expected_found=sum(task.expected_found for task in tasks),
        expected_total=sum(task.expected_total for task in tasks),
        context_expected_found=sum(task.context_expected_found for task in tasks),
        mean_reciprocal_rank=f"{reciprocal_rank.numerator}/{reciprocal_rank.denominator}",
        irrelevant_candidates=sum(task.irrelevant_candidates for task in tasks),
        expanded_nodes=sum(len(task.expanded) for task in tasks),
        maximum_expanded_nodes=max(len(task.expanded) for task in tasks),
        boundary_leaks=sum(value in encoded for value in FORBIDDEN_FIXTURE_VALUES),
    )


def _failed_criteria(value: StrategyAggregate) -> tuple[str, ...]:
    failed: list[str] = []
    if (
        value.fixture_hits_at_10 != 3
        or value.fixture_tasks != 3
        or value.fixture_expected_found != 4
        or value.fixture_expected_total != 4
    ):
        failed.append("fixture-recall")
    if value.hits_at_10 < 9:
        failed.append("hits-at-10")
    if value.expected_found < 12:
        failed.append("direct-recall")
    if value.context_expected_found < 14:
        failed.append("context-recall")
    if Fraction(value.mean_reciprocal_rank) < Fraction(1, 2):
        failed.append("mean-reciprocal-rank")
    if value.irrelevant_candidates > 60:
        failed.append("irrelevant-candidates")
    if value.maximum_expanded_nodes > 10 or value.expanded_nodes > value.tasks * 5:
        failed.append("expansion-bound")
    if value.boundary_leaks:
        failed.append("boundary-leak")
    return tuple(failed)


def _is_source_node(node: IndexNode) -> bool:
    return node.path.startswith("src/")


def _source_module(path: str) -> str | None:
    parts = list(PurePosixPath(path).parts)
    if len(parts) < 2 or parts[0] != "src":
        return None
    parts = parts[1:]
    if parts[-1] == "__init__.py":
        parts.pop()
    else:
        parts[-1] = parts[-1].removesuffix(".py")
    return ".".join(parts) or None


def _target(node: IndexNode) -> Target:
    return Target(node.path, node.qualified_name)


def _node_key(node: IndexNode) -> tuple[str, int, str, str]:
    return node.path, _KIND_ORDER[node.kind], node.qualified_name, node.id
