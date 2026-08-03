from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import PurePosixPath, PureWindowsPath
from typing import Literal, TypeAlias

from silobrief.boundary_placeholders import (
    BoundaryMatcher,
    BoundaryPlaceholder,
    import_target,
)
from silobrief.python_structure import ImportEntry, ModuleStructure, SymbolUse
from silobrief.search_tokens import extract_source_text_tokens, normalize_search_tokens
from silobrief.sources import SourceFile, SourceSnapshot
from silobrief.state import BoundaryData, ConfigData

NodeKind: TypeAlias = Literal["module", "class", "function"]
EdgeKind: TypeAlias = Literal["contains", "import", "call", "reference"]


class IndexBuildError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class NodeTokens:
    path: tuple[str, ...]
    symbol: tuple[str, ...]
    imports: tuple[str, ...]
    comments: tuple[str, ...]
    docstrings: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class IndexNode:
    id: str
    kind: NodeKind
    name: str
    qualified_name: str
    path: str
    tokens: NodeTokens


@dataclass(frozen=True, slots=True)
class IndexEdge:
    source_id: str
    kind: EdgeKind
    target: str | BoundaryPlaceholder
    target_id: str | None


@dataclass(frozen=True, slots=True)
class IndexData:
    config_digest: str
    edges: tuple[IndexEdge, ...]
    index_version: int
    nodes: tuple[IndexNode, ...]
    source_digest: str
    stale: bool


@dataclass(frozen=True, slots=True)
class _ModuleContext:
    module_id: str
    module_name: str
    structure: ModuleStructure
    definition_nodes: tuple[IndexNode, ...]
    context_ids: dict[str, str]
    path_tokens: tuple[str, ...]
    import_tokens: tuple[str, ...]
    comment_tokens: tuple[str, ...]
    docstring_tokens: tuple[str, ...]
    boundary_matcher: BoundaryMatcher


def stable_node_id(path: str, kind: NodeKind, qualified_name: str) -> str:
    _validate_relative_path(path)
    if not qualified_name:
        raise IndexBuildError("node qualified name must not be empty")
    canonical = "\0".join((path, kind, qualified_name)).encode("utf-8")
    return f"node-{hashlib.sha256(canonical).hexdigest()}"


def build_index(
    snapshot: SourceSnapshot,
    structures: tuple[ModuleStructure, ...],
    config: ConfigData,
) -> IndexData:
    sources = _source_map(snapshot.files)
    modules = _module_map(structures)
    if set(sources) != set(modules):
        raise IndexBuildError("source and structure paths do not match")

    contexts: dict[str, _ModuleContext] = {}
    all_nodes: list[IndexNode] = []
    global_targets: dict[str, str] = {}
    for path in sorted(sources):
        context = _build_module_context(
            sources[path],
            modules[path],
            tuple(config["boundaries"]),
        )
        contexts[path] = context
        module_node = _module_node(context)
        all_nodes.append(module_node)
        all_nodes.extend(context.definition_nodes)
        global_targets.setdefault(context.module_name, context.module_id)
        for qualified_name, node_id in context.context_ids.items():
            global_targets.setdefault(f"{context.module_name}.{qualified_name}", node_id)

    edges: set[IndexEdge] = set()
    for path in sorted(contexts):
        context = contexts[path]
        _add_containment_edges(edges, context)
        _add_import_edges(edges, context, global_targets)
        _add_use_edges(edges, context, context.structure.calls, "call", global_targets)
        _add_use_edges(edges, context, context.structure.references, "reference", global_targets)

    return IndexData(
        config_digest=_config_digest(config),
        edges=tuple(sorted(edges, key=_edge_key)),
        index_version=1,
        nodes=tuple(sorted(all_nodes, key=_node_key)),
        source_digest=snapshot.digest,
        stale=False,
    )


def render_index_json(index: IndexData) -> bytes:
    value: dict[str, object] = {
        "config_digest": index.config_digest,
        "edges": [_edge_value(edge) for edge in index.edges],
        "index_version": index.index_version,
        "nodes": [_node_value(node) for node in index.nodes],
        "source_digest": index.source_digest,
        "stale": index.stale,
    }
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _build_module_context(
    source: SourceFile,
    structure: ModuleStructure,
    boundaries: tuple[BoundaryData, ...],
) -> _ModuleContext:
    module_name = _module_name(source.path)
    module_id = stable_node_id(source.path, "module", module_name)
    text_tokens = extract_source_text_tokens(source)
    path_tokens = normalize_search_tokens(source.path.removesuffix(".py"))
    boundary_matcher = BoundaryMatcher(source.path, structure.imports, boundaries)
    import_tokens = normalize_search_tokens(
        *_import_search_values(structure.imports, boundary_matcher)
    )

    definition_nodes: list[IndexNode] = []
    context_ids: dict[str, str] = {}
    seen_ids: set[str] = set()
    for definition in structure.definitions:
        node_id = stable_node_id(source.path, definition.kind, definition.qualified_name)
        context_ids.setdefault(definition.qualified_name, node_id)
        if node_id in seen_ids:
            continue
        seen_ids.add(node_id)
        definition_nodes.append(
            IndexNode(
                id=node_id,
                kind=definition.kind,
                name=definition.name,
                qualified_name=definition.qualified_name,
                path=source.path,
                tokens=NodeTokens(
                    path=path_tokens,
                    symbol=normalize_search_tokens(definition.qualified_name),
                    imports=import_tokens,
                    comments=text_tokens.comments,
                    docstrings=text_tokens.docstrings,
                ),
            )
        )
    return _ModuleContext(
        module_id=module_id,
        module_name=module_name,
        structure=structure,
        definition_nodes=tuple(definition_nodes),
        context_ids=context_ids,
        path_tokens=path_tokens,
        import_tokens=import_tokens,
        comment_tokens=text_tokens.comments,
        docstring_tokens=text_tokens.docstrings,
        boundary_matcher=boundary_matcher,
    )


def _module_node(context: _ModuleContext) -> IndexNode:
    return IndexNode(
        id=context.module_id,
        kind="module",
        name=context.module_name.rsplit(".", 1)[-1],
        qualified_name=context.module_name,
        path=context.structure.path,
        tokens=NodeTokens(
            path=context.path_tokens,
            symbol=normalize_search_tokens(context.module_name),
            imports=context.import_tokens,
            comments=context.comment_tokens,
            docstrings=context.docstring_tokens,
        ),
    )


def _add_containment_edges(edges: set[IndexEdge], context: _ModuleContext) -> None:
    for node in context.definition_nodes:
        parent_name, separator, _ = node.qualified_name.rpartition(".")
        source_id = (
            context.context_ids.get(parent_name, context.module_id)
            if separator
            else context.module_id
        )
        edges.add(IndexEdge(source_id, "contains", node.qualified_name, node.id))


def _add_import_edges(
    edges: set[IndexEdge],
    context: _ModuleContext,
    global_targets: dict[str, str],
) -> None:
    for imported in context.structure.imports:
        source_id = _context_id(context, imported.context)
        placeholder = context.boundary_matcher.match_import(imported)
        if placeholder is not None:
            target: str | BoundaryPlaceholder = placeholder
            target_id = None
        else:
            target = import_target(imported)
            target_id = global_targets.get(target)
        edges.add(IndexEdge(source_id, "import", target, target_id))


def _add_use_edges(
    edges: set[IndexEdge],
    context: _ModuleContext,
    uses: tuple[SymbolUse, ...],
    kind: Literal["call", "reference"],
    global_targets: dict[str, str],
) -> None:
    for use in uses:
        source_id = _context_id(context, use.context)
        placeholder = context.boundary_matcher.match_use(use.target, use.context)
        target: str | BoundaryPlaceholder = placeholder or use.target
        target_id = (
            None
            if placeholder is not None
            else _resolve_target(context, use.context, use.target, global_targets)
        )
        edges.add(IndexEdge(source_id, kind, target, target_id))


def _resolve_target(
    context: _ModuleContext,
    source_context: str | None,
    target: str,
    global_targets: dict[str, str],
) -> str | None:
    if source_context is not None and target.startswith("self."):
        owner, separator, _ = source_context.rpartition(".")
        if separator:
            candidate = f"{owner}.{target.removeprefix('self.')}"
            if candidate in context.context_ids:
                return context.context_ids[candidate]

    if source_context is not None:
        parts = source_context.split(".")
        for length in range(len(parts) - 1, -1, -1):
            prefix = ".".join(parts[:length])
            candidate = f"{prefix}.{target}" if prefix else target
            if candidate in context.context_ids:
                return context.context_ids[candidate]
    if target in context.context_ids:
        return context.context_ids[target]
    return global_targets.get(target)


def _context_id(context: _ModuleContext, qualified_name: str | None) -> str:
    if qualified_name is None:
        return context.module_id
    try:
        return context.context_ids[qualified_name]
    except KeyError as error:
        raise IndexBuildError(f"unknown source context: {qualified_name}") from error


def _module_name(path: str) -> str:
    _validate_relative_path(path)
    parts = list(PurePosixPath(path).parts)
    filename = parts[-1]
    if filename == "__init__.py" and len(parts) > 1:
        parts.pop()
    else:
        parts[-1] = filename.removesuffix(".py")
    return ".".join(parts)


def _import_search_values(
    imports: tuple[ImportEntry, ...],
    boundary_matcher: BoundaryMatcher,
) -> tuple[str, ...]:
    values: list[str] = []
    for imported in imports:
        placeholder = boundary_matcher.match_import(imported)
        if placeholder is not None:
            values.extend((placeholder.alias, placeholder.description))
        else:
            values.append(import_target(imported))
        if placeholder is None and imported.alias is not None:
            values.append(imported.alias)
    return tuple(values)


def _source_map(files: tuple[SourceFile, ...]) -> dict[str, SourceFile]:
    result = {source.path: source for source in files}
    if len(result) != len(files):
        raise IndexBuildError("source snapshot contains duplicate paths")
    return result


def _module_map(structures: tuple[ModuleStructure, ...]) -> dict[str, ModuleStructure]:
    result = {module.path: module for module in structures}
    if len(result) != len(structures):
        raise IndexBuildError("structure input contains duplicate paths")
    return result


def _config_digest(config: ConfigData) -> str:
    boundaries = sorted(
        config["boundaries"],
        key=lambda item: (item["path"], item["alias"], item["description"]),
    )
    value: dict[str, object] = {
        "boundaries": [dict(boundary) for boundary in boundaries],
        "default_excludes": sorted(config["default_excludes"]),
        "schema_version": config["schema_version"],
    }
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _node_value(node: IndexNode) -> dict[str, object]:
    return {
        "id": node.id,
        "kind": node.kind,
        "name": node.name,
        "path": node.path,
        "qualified_name": node.qualified_name,
        "tokens": {
            "comments": list(node.tokens.comments),
            "docstrings": list(node.tokens.docstrings),
            "imports": list(node.tokens.imports),
            "path": list(node.tokens.path),
            "symbol": list(node.tokens.symbol),
        },
    }


def _edge_value(edge: IndexEdge) -> dict[str, object]:
    return {
        "kind": edge.kind,
        "source_id": edge.source_id,
        "target": _edge_target_value(edge.target),
        "target_id": edge.target_id,
    }


def _edge_target_value(target: str | BoundaryPlaceholder) -> object:
    if isinstance(target, str):
        return target
    return {
        "alias": target.alias,
        "description": target.description,
        "kind": "boundary-placeholder",
    }


def _node_key(node: IndexNode) -> tuple[str, int, str, str]:
    kind_order = {"module": 0, "class": 1, "function": 2}
    return node.path, kind_order[node.kind], node.qualified_name, node.id


def _edge_key(edge: IndexEdge) -> tuple[str, str, str, str]:
    if isinstance(edge.target, str):
        target = f"public:{edge.target}"
    else:
        target = f"boundary:{edge.target.alias}:{edge.target.description}"
    return edge.source_id, edge.kind, target, edge.target_id or ""


def _validate_relative_path(path: str) -> None:
    posix = PurePosixPath(path)
    windows = PureWindowsPath(path)
    if (
        not path
        or "\\" in path
        or posix.is_absolute()
        or windows.drive
        or windows.root
        or ".." in posix.parts
        or posix.as_posix() != path
    ):
        raise IndexBuildError("node path must be a normalized relative POSIX path")
