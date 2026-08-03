from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from silobrief import sources
from silobrief.boundary_placeholders import BoundaryPlaceholder
from silobrief.index import (
    EdgeKind,
    IndexBuildError,
    IndexData,
    IndexEdge,
    IndexNode,
    NodeKind,
    NodeTokens,
    config_digest,
    render_index_json,
    stable_node_id,
)
from silobrief.sources import SourceCollectionError, SourceWarning
from silobrief.state import STATE_DIRECTORY, find_project_root, is_valid_boundary_alias, load_config

_DIGEST = re.compile(r"[0-9a-f]{64}")
_KINDS = ("module", "class", "function")
_EDGE_KINDS = ("contains", "import", "call", "reference")
_KIND_ORDER = {"module": 0, "class": 1, "function": 2}


class StoredIndexError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class LoadedIndex:
    root: Path
    index: IndexData
    warnings: tuple[SourceWarning, ...]


def load_current_index(start: Path) -> LoadedIndex:
    root = find_project_root(start, validate_index=False)
    config = load_config(root, validate_index=False)
    index = _read_index(root)
    if index.stale:
        raise StoredIndexError("index.json is stale; run sb init")
    if index.config_digest != config_digest(config):
        raise StoredIndexError("index.json does not match the current config")
    try:
        snapshot = sources.snapshot_sources(root, config)
    except SourceCollectionError as error:
        raise StoredIndexError("cannot check index source currentness") from error
    if index.source_digest != snapshot.digest:
        raise StoredIndexError("index.json does not match the current source")
    return LoadedIndex(root=root, index=index, warnings=snapshot.warnings)


def _read_index(root: Path) -> IndexData:
    path = root / STATE_DIRECTORY / "index.json"
    if path.is_symlink() or not path.is_file():
        raise StoredIndexError("index.json must be a real file; run sb init")
    try:
        content = path.read_bytes()
        value: object = json.loads(content)
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise StoredIndexError("cannot read index.json") from error
    index = _index(value)
    if render_index_json(index) != content:
        raise StoredIndexError("index.json is not in canonical UTF-8/LF form")
    return index


def _index(value: object) -> IndexData:
    data = _object(
        value,
        {"config_digest", "edges", "index_version", "nodes", "source_digest", "stale"},
    )
    if type(data["index_version"]) is not int or data["index_version"] != 1:
        raise StoredIndexError("index.json has an unsupported version")
    if type(data["stale"]) is not bool:
        raise StoredIndexError("index.json stale flag is invalid")
    nodes = tuple(_node(item) for item in _array(data["nodes"]))
    edges = tuple(_edge(item) for item in _array(data["edges"]))
    _validate_graph(nodes, edges)
    return IndexData(
        config_digest=_digest(data["config_digest"]),
        edges=edges,
        index_version=1,
        nodes=nodes,
        source_digest=_digest(data["source_digest"]),
        stale=data["stale"],
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
        placeholder = _object(target_value, {"alias", "description", "kind"})
        if placeholder["kind"] != "boundary-placeholder":
            raise StoredIndexError("index.json boundary placeholder is invalid")
        alias = _text(placeholder["alias"])
        if not is_valid_boundary_alias(alias):
            raise StoredIndexError("index.json boundary alias is invalid")
        target = BoundaryPlaceholder(
            alias=alias,
            description=_text(placeholder["description"]),
        )
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


def _validate_graph(nodes: tuple[IndexNode, ...], edges: tuple[IndexEdge, ...]) -> None:
    node_ids = {node.id for node in nodes}
    if len(node_ids) != len(nodes) or nodes != tuple(sorted(nodes, key=_node_key)):
        raise StoredIndexError("index.json nodes are duplicated or unordered")
    if len(set(edges)) != len(edges) or edges != tuple(sorted(edges, key=_edge_key)):
        raise StoredIndexError("index.json edges are duplicated or unordered")
    for edge in edges:
        if edge.source_id not in node_ids or (
            edge.target_id is not None and edge.target_id not in node_ids
        ):
            raise StoredIndexError("index.json edge references an unknown node")


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
