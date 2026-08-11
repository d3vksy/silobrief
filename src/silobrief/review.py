from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal, TypeAlias

from silobrief.index import EdgeKind, IndexData, IndexNode, NodeKind
from silobrief.ranking import RankedCandidate, RankEvidence

_MAX_OPTIONS = 10
_MAX_RELATED_OPTIONS = 10
_KIND_ORDER = {"module": 0, "class": 1, "function": 2}
ContextRelation: TypeAlias = Literal[
    "calls",
    "called-by",
    "imports",
    "imported-by",
    "references",
    "referenced-by",
    "contains",
    "contained-by",
]
_RELATION_ORDER: dict[ContextRelation, int] = {
    "calls": 0,
    "called-by": 1,
    "imports": 2,
    "imported-by": 3,
    "references": 4,
    "referenced-by": 5,
    "contains": 6,
    "contained-by": 7,
}
_OUTGOING_RELATION: dict[EdgeKind, ContextRelation] = {
    "call": "calls",
    "import": "imports",
    "reference": "references",
    "contains": "contains",
}
_INCOMING_RELATION: dict[EdgeKind, ContextRelation] = {
    "call": "called-by",
    "import": "imported-by",
    "reference": "referenced-by",
    "contains": "contained-by",
}


class ReviewError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ReviewNode:
    id: str
    path: str
    kind: NodeKind
    name: str
    qualified_name: str
    relations: tuple[ContextRelation, ...] = ()


@dataclass(frozen=True, slots=True)
class CandidateOption:
    number: int
    node: ReviewNode
    score: int
    evidence: RankEvidence


@dataclass(frozen=True, slots=True)
class SymbolOption:
    number: int
    node: ReviewNode


@dataclass(frozen=True, slots=True)
class DisclosureChoices:
    paths: bool
    symbols: bool
    public_libraries: bool
    human_notes: bool
    boundary_placeholders: bool


@dataclass(frozen=True, slots=True)
class ReviewSelection:
    selected: tuple[ReviewNode, ...]
    expanded: tuple[ReviewNode, ...]
    fields: DisclosureChoices


def candidate_options(candidates: tuple[RankedCandidate, ...]) -> tuple[CandidateOption, ...]:
    ordered = sorted(candidates, key=_ranked_key)
    seen: set[str] = set()
    options: list[CandidateOption] = []
    for candidate in ordered:
        if candidate.node.id in seen:
            raise ReviewError("ranked candidates contain duplicate nodes")
        seen.add(candidate.node.id)
        options.append(
            CandidateOption(
                number=len(options) + 1,
                node=_review_node(candidate.node),
                score=candidate.score,
                evidence=candidate.evidence,
            )
        )
    return tuple(options[:_MAX_OPTIONS])


def selector_symbol_options(
    index: IndexData,
    selector: str,
) -> tuple[SymbolOption, ...] | None:
    nodes = _node_map(index)
    if selector in nodes:
        return None
    modules = _module_path_map(nodes.values())
    if selector not in modules:
        raise ReviewError("file path or node ID is not present in the current index")
    symbols = sorted(
        (
            _review_node(node)
            for node in nodes.values()
            if node.path == selector and node.kind != "module"
        ),
        key=_symbol_outline_key,
    )
    return tuple(SymbolOption(number, node) for number, node in enumerate(symbols, start=1))


def review_selection(
    index: IndexData,
    options: tuple[CandidateOption, ...],
    *,
    selected_numbers: tuple[int, ...],
    added: tuple[str, ...],
    excluded: tuple[str, ...],
    fields: DisclosureChoices,
) -> ReviewSelection:
    nodes = _node_map(index)
    modules = _module_path_map(nodes.values())
    option_by_number = _option_map(options, nodes)
    selected_ids = {_selected_id(number, option_by_number) for number in selected_numbers}
    selected_ids.update(_resolve_selector(selector, nodes, modules) for selector in added)
    excluded_ids = {_resolve_selector(selector, nodes, modules) for selector in excluded}
    selected_ids.difference_update(excluded_ids)
    if not selected_ids:
        raise ReviewError("start selection is empty")

    related = _related_nodes(index, selected_ids, set(nodes))
    for node_id in selected_ids | excluded_ids:
        related.pop(node_id, None)
    return ReviewSelection(
        selected=_ordered_review_nodes(selected_ids, nodes),
        expanded=_ordered_related_nodes(related, nodes),
        fields=fields,
    )


def _node_map(index: IndexData) -> dict[str, IndexNode]:
    nodes = {node.id: node for node in index.nodes}
    if len(nodes) != len(index.nodes):
        raise ReviewError("current index contains duplicate node IDs")
    return nodes


def _module_path_map(nodes: Iterable[IndexNode]) -> dict[str, str]:
    modules: dict[str, str] = {}
    for node in nodes:
        if node.kind != "module":
            continue
        if node.path in modules:
            raise ReviewError("current index contains duplicate module paths")
        modules[node.path] = node.id
    return modules


def _option_map(
    options: tuple[CandidateOption, ...],
    nodes: dict[str, IndexNode],
) -> dict[int, CandidateOption]:
    result: dict[int, CandidateOption] = {}
    for option in options:
        indexed = nodes.get(option.node.id)
        if indexed is None or _review_node(indexed) != option.node:
            raise ReviewError("candidate does not belong to the current index")
        if option.number < 1 or option.number in result:
            raise ReviewError("candidate numbers must be unique positive integers")
        result[option.number] = option
    return result


def _selected_id(number: int, options: dict[int, CandidateOption]) -> str:
    try:
        return options[number].node.id
    except KeyError as error:
        raise ReviewError(f"unknown candidate number: {number}") from error


def _resolve_selector(
    selector: str,
    nodes: dict[str, IndexNode],
    modules: dict[str, str],
) -> str:
    if selector in nodes:
        return selector
    if selector in modules:
        return modules[selector]
    raise ReviewError(f"unknown node ID or path selector: {selector}")


def _related_nodes(
    index: IndexData,
    selected_ids: set[str],
    node_ids: set[str],
) -> dict[str, set[ContextRelation]]:
    related: dict[str, set[ContextRelation]] = {}
    for edge in index.edges:
        target_id = edge.target_id
        if (
            edge.source_id not in node_ids
            or target_id not in node_ids
            or edge.source_id == target_id
        ):
            continue
        if edge.source_id in selected_ids:
            related.setdefault(target_id, set()).add(_OUTGOING_RELATION[edge.kind])
        if target_id in selected_ids:
            related.setdefault(edge.source_id, set()).add(_INCOMING_RELATION[edge.kind])
    return related


def _expanded_ids(
    index: IndexData,
    selected_ids: set[str],
    node_ids: set[str],
) -> set[str]:
    """Preserve the frozen v0.6 benchmark target while review uses labeled relations."""
    return set(_related_nodes(index, selected_ids, node_ids))


def _ordered_related_nodes(
    relations: dict[str, set[ContextRelation]],
    nodes: dict[str, IndexNode],
) -> tuple[ReviewNode, ...]:
    ordered = sorted(relations, key=lambda node_id: _index_node_key(nodes[node_id]))
    return tuple(
        _review_node(
            nodes[node_id],
            tuple(sorted(relations[node_id], key=_RELATION_ORDER.__getitem__)),
        )
        for node_id in ordered[:_MAX_RELATED_OPTIONS]
    )


def _ordered_review_nodes(
    node_ids: set[str],
    nodes: dict[str, IndexNode],
) -> tuple[ReviewNode, ...]:
    selected = (_review_node(nodes[node_id]) for node_id in node_ids)
    return tuple(sorted(selected, key=_review_node_key))


def _review_node(
    node: IndexNode,
    relations: tuple[ContextRelation, ...] = (),
) -> ReviewNode:
    return ReviewNode(
        id=node.id,
        path=node.path,
        kind=node.kind,
        name=node.name,
        qualified_name=node.qualified_name,
        relations=relations,
    )


def _ranked_key(candidate: RankedCandidate) -> tuple[int, str, int, str, str, str]:
    return (-candidate.score, *_index_node_key(candidate.node))


def _index_node_key(node: IndexNode) -> tuple[str, int, str, str, str]:
    return node.path, _KIND_ORDER[node.kind], node.name, node.qualified_name, node.id


def _review_node_key(node: ReviewNode) -> tuple[str, int, str, str, str]:
    return node.path, _KIND_ORDER[node.kind], node.name, node.qualified_name, node.id


def _symbol_outline_key(node: ReviewNode) -> tuple[str, int, str]:
    return node.qualified_name, _KIND_ORDER[node.kind], node.id
