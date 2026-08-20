from __future__ import annotations

import json
import re
from pathlib import Path
from typing import cast

from silobrief.boundary_placeholders import BoundaryPlaceholder
from silobrief.index import (
    BoundaryDisclosure,
    EdgeKind,
    IndexBuildError,
    IndexData,
    IndexEdge,
    IndexNode,
    NodeKind,
    NodeTokens,
    render_index_json,
    stable_node_id,
)
from silobrief.index_version import (
    INDEX_VERSION,
    is_current_index_version,
    is_rebuildable_index_version,
)
from silobrief.path_safety import is_link_like
from silobrief.state import STATE_DIRECTORY, is_valid_boundary_alias

_DIGEST = re.compile(r"[0-9a-f]{64}")
_KINDS = ("module", "class", "function")
_EDGE_KINDS = ("contains", "import", "call", "reference")
_KIND_ORDER = {"module": 0, "class": 1, "function": 2}


class StoredIndexError(ValueError):
    pass


def load_stored_index(root: Path) -> IndexData:
    path = root / STATE_DIRECTORY / "index.json"
    if is_link_like(path) or not path.is_file():
        raise StoredIndexError("index.json must be a real file; run sb init")
    try:
        content = path.read_bytes()
    except OSError as error:
        raise StoredIndexError("cannot read index.json") from error
    return parse_stored_index(content)


def parse_stored_index(content: bytes) -> IndexData:
    try:
        value: object = json.loads(content)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise StoredIndexError("cannot read index.json") from error
    index = _index(value)
    if render_index_json(index) != content:
        raise StoredIndexError("index.json is not in canonical UTF-8/LF form")
    return index


def _index(value: object) -> IndexData:
    if not isinstance(value, dict):
        raise StoredIndexError("index.json object schema is invalid")
    unvalidated = cast(dict[str, object], value)
    index_version = unvalidated.get("index_version")
    if is_rebuildable_index_version(index_version) and not is_current_index_version(index_version):
        raise StoredIndexError("index.json uses an outdated version; run sb init")
    if not is_current_index_version(index_version):
        raise StoredIndexError("index.json has an unsupported version")
    data = _object(
        value,
        {
            "boundary_disclosures",
            "config_digest",
            "edges",
            "index_version",
            "nodes",
            "source_digest",
            "stale",
        },
    )
    if type(data["stale"]) is not bool:
        raise StoredIndexError("index.json stale flag is invalid")
    nodes = tuple(_node(item) for item in _array(data["nodes"]))
    edges = tuple(_edge(item) for item in _array(data["edges"]))
    boundary_disclosures = tuple(
        _boundary_disclosure(item) for item in _array(data["boundary_disclosures"])
    )
    _validate_graph(nodes, edges, boundary_disclosures)
    return IndexData(
        config_digest=_digest(data["config_digest"]),
        edges=edges,
        index_version=INDEX_VERSION,
        nodes=nodes,
        source_digest=_digest(data["source_digest"]),
        stale=data["stale"],
        boundary_disclosures=boundary_disclosures,
    )


def _node(value: object) -> IndexNode:
    data = _object(value, {"id", "kind", "name", "path", "qualified_name", "tokens"})
    kind = cast(NodeKind, _choice(data["kind"], _KINDS))
    path = _text(data["path"])
    qualified_name = _text(data["qualified_name"])
    node_id = _text(data["id"])
    try:
        expected_id = stable_node_id(path, kind, qualified_name)
    except IndexBuildError as error:
        raise StoredIndexError("index.json node path is invalid") from error
    if node_id != expected_id:
        raise StoredIndexError("index.json node ID is invalid")
    name = _text(data["name"])
    if name != qualified_name.rsplit(".", 1)[-1]:
        raise StoredIndexError("index.json node name is invalid")
    tokens = _object(data["tokens"], {"comments", "docstrings", "imports", "path", "symbol"})
    return IndexNode(
        id=node_id,
        kind=kind,
        name=name,
        qualified_name=qualified_name,
        path=path,
        tokens=NodeTokens(
            path=_tokens(tokens["path"]),
            symbol=_tokens(tokens["symbol"]),
            imports=_tokens(tokens["imports"]),
            comments=_tokens(tokens["comments"]),
            docstrings=_tokens(tokens["docstrings"]),
        ),
    )


def _edge(value: object) -> IndexEdge:
    data = _object(value, {"kind", "source_id", "target", "target_id"})
    target_value = data["target"]
    if isinstance(target_value, str):
        target: str | BoundaryPlaceholder = _text(target_value)
    else:
        target = _placeholder(target_value)
    target_id_value = data["target_id"]
    target_id = None if target_id_value is None else _text(target_id_value)
    if isinstance(target, BoundaryPlaceholder) and target_id is not None:
        raise StoredIndexError("index.json boundary target ID is invalid")
    return IndexEdge(
        source_id=_text(data["source_id"]),
        kind=cast(EdgeKind, _choice(data["kind"], _EDGE_KINDS)),
        target=target,
        target_id=target_id,
    )


def _boundary_disclosure(value: object) -> BoundaryDisclosure:
    data = _object(value, {"node_id", "placeholder"})
    return BoundaryDisclosure(
        node_id=_text(data["node_id"]),
        placeholder=_placeholder(data["placeholder"]),
    )


def _placeholder(value: object) -> BoundaryPlaceholder:
    placeholder = _object(value, {"alias", "description", "kind"})
    if placeholder["kind"] != "boundary-placeholder":
        raise StoredIndexError("index.json boundary placeholder is invalid")
    alias = _text(placeholder["alias"])
    if not is_valid_boundary_alias(alias):
        raise StoredIndexError("index.json boundary alias is invalid")
    return BoundaryPlaceholder(
        alias=alias,
        description=_text(placeholder["description"]),
    )


def _validate_graph(
    nodes: tuple[IndexNode, ...],
    edges: tuple[IndexEdge, ...],
    boundary_disclosures: tuple[BoundaryDisclosure, ...],
) -> None:
    node_ids = {node.id for node in nodes}
    node_kinds = {node.id: node.kind for node in nodes}
    if len(node_ids) != len(nodes) or nodes != tuple(sorted(nodes, key=_node_key)):
        raise StoredIndexError("index.json nodes are duplicated or unordered")
    if len(set(edges)) != len(edges) or edges != tuple(sorted(edges, key=_edge_key)):
        raise StoredIndexError("index.json edges are duplicated or unordered")
    if len(set(boundary_disclosures)) != len(boundary_disclosures) or boundary_disclosures != tuple(
        sorted(boundary_disclosures, key=_disclosure_key)
    ):
        raise StoredIndexError("index.json boundary disclosures are duplicated or unordered")
    for edge in edges:
        if edge.source_id not in node_ids or (
            edge.target_id is not None and edge.target_id not in node_ids
        ):
            raise StoredIndexError("index.json edge references an unknown node")
    parents = {
        edge.target_id: edge.source_id
        for edge in edges
        if edge.kind == "contains" and edge.target_id is not None
    }
    boundary_sources: dict[BoundaryPlaceholder, set[str]] = {}
    for edge in edges:
        if isinstance(edge.target, BoundaryPlaceholder):
            boundary_sources.setdefault(edge.target, set()).add(edge.source_id)
    for disclosure in boundary_disclosures:
        if node_kinds.get(disclosure.node_id) not in {"class", "function"}:
            raise StoredIndexError("index.json boundary disclosure references an unknown node")
        ancestors: set[str] = set()
        current = disclosure.node_id
        while current in parents and current not in ancestors:
            current = parents[current]
            ancestors.add(current)
        if ancestors.isdisjoint(boundary_sources.get(disclosure.placeholder, set())):
            raise StoredIndexError("index.json boundary disclosure has no enclosing edge")


def _object(value: object, keys: set[str]) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != keys:
        raise StoredIndexError("index.json object schema is invalid")
    return cast(dict[str, object], value)


def _array(value: object) -> list[object]:
    if not isinstance(value, list):
        raise StoredIndexError("index.json array field is invalid")
    return cast(list[object], value)


def _text(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise StoredIndexError("index.json text field is invalid")
    return value


def _tokens(value: object) -> tuple[str, ...]:
    result = tuple(_text(item) for item in _array(value))
    if result != tuple(sorted(set(result))):
        raise StoredIndexError("index.json token array is invalid")
    return result


def _digest(value: object) -> str:
    text = _text(value)
    if _DIGEST.fullmatch(text) is None:
        raise StoredIndexError("index.json digest is invalid")
    return text


def _choice(value: object, allowed: tuple[str, ...]) -> str:
    text = _text(value)
    if text not in allowed:
        raise StoredIndexError("index.json enum field is invalid")
    return text


def _node_key(node: IndexNode) -> tuple[str, int, str, str]:
    return node.path, _KIND_ORDER[node.kind], node.qualified_name, node.id


def _edge_key(edge: IndexEdge) -> tuple[str, str, str, str]:
    target = (
        f"public:{edge.target}"
        if isinstance(edge.target, str)
        else f"boundary:{edge.target.alias}:{edge.target.description}"
    )
    return edge.source_id, edge.kind, target, edge.target_id or ""


def _disclosure_key(disclosure: BoundaryDisclosure) -> tuple[str, str, str]:
    return (
        disclosure.node_id,
        disclosure.placeholder.alias,
        disclosure.placeholder.description,
    )
