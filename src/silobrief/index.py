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
from silobrief.index_version import INDEX_VERSION, is_current_index_version
from silobrief.python_structure import (
    Definition,
    ImportEntry,
    ModuleStructure,
    StoreBinding,
    SymbolUse,
)
from silobrief.search_tokens import extract_scoped_source_text_tokens, normalize_search_tokens
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
class _ImportBinding:
    context: str | None
    visible: str
    target: str
    line: int
    column: int
    conditional: bool
    deferred: bool = False


@dataclass(frozen=True, slots=True)
class _StoreBinding:
    context: str | None
    name: str
    line: int
    column: int
    conditional: bool
    runtime: bool
    deferred: bool = False


@dataclass(frozen=True, slots=True)
class _ScopeBinding:
    target_id: str | None = None
    imported_target: str | None = None
    falls_through: bool = False
    unknown: bool = False


@dataclass(frozen=True, slots=True)
class _ModuleContext:
    module_id: str
    module_name: str
    structure: ModuleStructure
    definition_nodes: tuple[IndexNode, ...]
    context_ids: dict[str, str]
    import_bindings: tuple[_ImportBinding, ...]
    store_bindings: tuple[_StoreBinding, ...]
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
    src_is_package = "src/__init__.py" in sources
    for path in sorted(sources):
        context = _build_module_context(
            sources[path],
            modules[path],
            tuple(config["boundaries"]),
            src_is_package=src_is_package,
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
        config_digest=config_digest(config),
        edges=tuple(sorted(edges, key=_edge_key)),
        index_version=INDEX_VERSION,
        nodes=tuple(sorted(all_nodes, key=_node_key)),
        source_digest=snapshot.digest,
        stale=False,
    )


def render_index_json(index: IndexData) -> bytes:
    if not is_current_index_version(index.index_version):
        raise IndexBuildError("index does not use the current version")
    value: dict[str, object] = {
        "config_digest": index.config_digest,
        "edges": [_edge_value(edge) for edge in index.edges],
        "index_version": INDEX_VERSION,
        "nodes": [_node_value(node) for node in index.nodes],
        "source_digest": index.source_digest,
        "stale": index.stale,
    }
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _build_module_context(
    source: SourceFile,
    structure: ModuleStructure,
    boundaries: tuple[BoundaryData, ...],
    *,
    src_is_package: bool,
) -> _ModuleContext:
    module_name = _module_name(source.path, src_is_package=src_is_package)
    module_id = stable_node_id(source.path, "module", module_name)
    text_tokens = extract_scoped_source_text_tokens(source, structure.definitions)
    definition_tokens = dict(text_tokens.definitions)
    path_tokens = normalize_search_tokens(source.path.removesuffix(".py"))
    boundary_matcher = BoundaryMatcher(source.path, structure.imports, boundaries)
    import_tokens = normalize_search_tokens(
        *_import_search_values(structure.imports, boundary_matcher)
    )

    definition_nodes: list[IndexNode] = []
    context_ids: dict[str, str] = {}
    seen_ids: set[str] = set()
    for definition in structure.definitions:
        scoped_tokens = definition_tokens[definition.qualified_name]
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
                    comments=scoped_tokens.comments,
                    docstrings=scoped_tokens.docstrings,
                ),
            )
        )
    return _ModuleContext(
        module_id=module_id,
        module_name=module_name,
        structure=structure,
        definition_nodes=tuple(definition_nodes),
        context_ids=context_ids,
        import_bindings=_import_bindings(module_name, source.path, structure.imports),
        store_bindings=_store_bindings(structure.store_bindings),
        path_tokens=path_tokens,
        import_tokens=import_tokens,
        comment_tokens=text_tokens.module.comments,
        docstring_tokens=text_tokens.module.docstrings,
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
            resolved_target = _resolved_import_target(
                context.module_name, context.structure.path, imported
            )
            if resolved_target is None:
                resolved_target = import_target(imported)
            target = resolved_target
            target_id = global_targets.get(resolved_target)
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
        target, target_id = _resolve_use_target(
            context,
            use.context,
            use.target,
            use.line,
            use.column,
            use.skip_class_scope,
            use.synthetic_local,
            use.lookup_limit,
            global_targets,
        )
        edges.add(IndexEdge(source_id, kind, target, target_id))


def _resolve_use_target(
    context: _ModuleContext,
    source_context: str | None,
    target: str,
    line: int,
    column: int,
    skip_class_scope: bool,
    synthetic_local: bool,
    lookup_limit: tuple[int, int] | None,
    global_targets: dict[str, str],
) -> tuple[str | BoundaryPlaceholder, str | None]:
    if synthetic_local:
        return target, None
    use_position = (line, column, 3)
    possible: list[_ScopeBinding] = []
    saw_binding = False
    for scope in _lexical_scopes(context, source_context, target, line, skip_class_scope):
        bindings = _resolve_scope_bindings(
            context,
            scope,
            source_context,
            target,
            line,
            use_position,
            lookup_limit,
        )
        if bindings is None:
            continue
        saw_binding = True
        for binding in bindings:
            if binding.imported_target is None:
                continue
            placeholder = context.boundary_matcher.match_resolved(binding.imported_target)
            if placeholder is not None:
                return placeholder, None
        possible.extend(binding for binding in bindings if not binding.falls_through)
        if not any(binding.falls_through for binding in bindings):
            return _binding_result(target, possible, global_targets)
    direct_placeholder = context.boundary_matcher.match_resolved(target)
    if direct_placeholder is not None:
        return direct_placeholder, None
    if saw_binding:
        possible.append(_ScopeBinding())
        return _binding_result(target, possible, global_targets)
    return target, None


def _lexical_scopes(
    context: _ModuleContext,
    source_context: str | None,
    target: str,
    line: int,
    skip_class_scope: bool,
) -> tuple[str | None, ...]:
    if source_context is None:
        return (None,)
    root = target.split(".", 1)[0]
    result: list[str | None] = []
    current: str | None = source_context
    nonlocal_lookup = False
    while current is not None:
        definition = _definition_at(context, current, line)
        kind = definition.kind if definition is not None else None
        hidden_class = skip_class_scope and kind == "class"
        visible = kind == "function" or current == source_context and not hidden_class
        if visible:
            result.append(current)
            if _has_declaration(context, current, line, root, "global"):
                if not nonlocal_lookup:
                    result.append(None)
                return tuple(result)
            if _has_declaration(context, current, line, root, "nonlocal"):
                nonlocal_lookup = True
        current = _structural_parent(current)
    if not nonlocal_lookup:
        result.append(None)
    return tuple(result)


def _resolve_scope_bindings(
    context: _ModuleContext,
    scope: str | None,
    source_context: str | None,
    target: str,
    line: int,
    use_position: tuple[int, int, int],
    definition_under_construction: tuple[int, int] | None,
) -> tuple[_ScopeBinding, ...] | None:
    root = target.split(".", 1)[0]
    scope_definition = _definition_at(context, scope, line) if scope is not None else None
    candidates: list[tuple[tuple[int, int, int], _ScopeBinding, bool]] = []
    deferred_bindings: list[_ScopeBinding] = []
    for candidate_definition in context.structure.definitions:
        if (
            _structural_parent(candidate_definition.qualified_name) != scope
            or candidate_definition.name != root
            or not _inside_definition(scope_definition, candidate_definition.line)
            or definition_under_construction
            == (candidate_definition.line, candidate_definition.column)
        ):
            continue
        suffix = target[len(root) :]
        if suffix and candidate_definition.kind == "class":
            target_id = context.context_ids.get(f"{candidate_definition.qualified_name}{suffix}")
        elif suffix:
            target_id = None
        else:
            target_id = stable_node_id(
                context.structure.path,
                candidate_definition.kind,
                candidate_definition.qualified_name,
            )
        candidates.append(
            (
                (candidate_definition.line, candidate_definition.column, 0),
                _ScopeBinding(target_id=target_id, unknown=target_id is None),
                candidate_definition.conditional,
            )
        )
    for import_binding in context.import_bindings:
        if import_binding.context != scope or not _inside_definition(
            scope_definition, import_binding.line
        ):
            continue
        imported_target = _imported_target(import_binding, target)
        if imported_target is None:
            continue
        candidate = (
            (import_binding.line, import_binding.column, 1),
            _ScopeBinding(imported_target=imported_target),
            import_binding.conditional,
        )
        if import_binding.deferred:
            deferred_bindings.append(candidate[1])
        else:
            candidates.append(candidate)
    for store_binding in context.store_bindings:
        if (
            not store_binding.runtime
            or store_binding.context != scope
            or store_binding.name != root
            or not _inside_definition(scope_definition, store_binding.line)
        ):
            continue
        candidate = (
            (store_binding.line, store_binding.column, 2),
            _ScopeBinding(unknown=True),
            store_binding.conditional,
        )
        if store_binding.deferred:
            deferred_bindings.append(candidate[1])
        else:
            candidates.append(candidate)
    if (parameter := _parameter_binding(context, scope, target, line)) is not None:
        candidates.append(((0, 0, 0), parameter, False))

    direct_scope = scope == source_context
    declared = _has_declaration(context, scope, line, root, "global") or _has_declaration(
        context, scope, line, root, "nonlocal"
    )
    static_local = (
        not declared
        and scope_definition is not None
        and scope_definition.kind == "function"
        and any(
            item.context == scope
            and item.name == root
            and _inside_definition(scope_definition, item.line)
            for item in context.store_bindings
        )
    )
    falls_through = declared or (
        direct_scope and scope_definition is not None and scope_definition.kind == "class"
    )
    visible_candidates = candidates
    if direct_scope:
        visible_candidates = [candidate for candidate in candidates if candidate[0] <= use_position]
    if visible_candidates:
        if direct_scope:
            possible = list(_possible_bindings(visible_candidates, falls_through))
        else:
            entry_position = _scope_entry_position(context, scope, source_context, line)
            missing = _ScopeBinding(falls_through=falls_through)
            if entry_position is None:
                possible = [missing, *(item[1] for item in candidates)]
            else:
                before = [item for item in visible_candidates if item[0] < entry_position]
                possible = list(_possible_bindings(before, falls_through)) if before else [missing]
                possible.extend(item[1] for item in visible_candidates if item[0] >= entry_position)
        possible.extend(deferred_bindings)
        return tuple(dict.fromkeys(possible))

    if (
        direct_scope
        and (candidates or static_local)
        and not declared
        and (scope is None or scope_definition is not None and scope_definition.kind == "function")
    ):
        return tuple(dict.fromkeys([_ScopeBinding(), *deferred_bindings]))
    if static_local:
        return tuple(dict.fromkeys([_ScopeBinding(unknown=True), *deferred_bindings]))
    if deferred_bindings:
        return tuple(dict.fromkeys([_ScopeBinding(falls_through=True), *deferred_bindings]))
    return None


def _possible_bindings(
    candidates: list[tuple[tuple[int, int, int], _ScopeBinding, bool]],
    missing_falls_through: bool = False,
) -> tuple[_ScopeBinding, ...]:
    possible: list[_ScopeBinding] = []
    for _, binding, conditional in sorted(candidates, key=lambda candidate: candidate[0]):
        if conditional:
            if not possible:
                possible.append(_ScopeBinding(falls_through=missing_falls_through))
            possible.append(binding)
        else:
            possible = [binding]
    return tuple(dict.fromkeys(possible))


def _binding_result(
    target: str,
    bindings: list[_ScopeBinding],
    global_targets: dict[str, str],
) -> tuple[str, str | None]:
    concrete = tuple(
        binding
        for binding in dict.fromkeys(bindings)
        if binding.target_id is not None or binding.imported_target is not None or binding.unknown
    )
    if len(concrete) != 1 or concrete[0].unknown:
        return target, None
    if concrete[0].imported_target is not None:
        imported_target = concrete[0].imported_target
        target_id = global_targets.get(imported_target)
        return (target, target_id) if target_id is not None else (imported_target, None)
    return target, concrete[0].target_id


def _scope_entry_position(
    context: _ModuleContext,
    scope: str | None,
    source_context: str | None,
    line: int,
) -> tuple[int, int, int] | None:
    if source_context is None:
        return None
    prefix = f"{scope}." if scope is not None else ""
    if not source_context.startswith(prefix):
        return None
    child = source_context[len(prefix) :].split(".", 1)[0]
    definition = _definition_at(context, f"{prefix}{child}", line)
    if definition is None:
        return None
    if definition.kind == "class" and source_context != definition.qualified_name:
        return (definition.end_line + 1, definition.column, 2)
    return (definition.line, definition.column, 2)


def _parameter_binding(
    context: _ModuleContext,
    scope: str | None,
    target: str,
    line: int,
) -> _ScopeBinding | None:
    if scope is None:
        return None
    receiver, separator, member = target.partition(".")
    definition = _definition_at(context, scope, line)
    if definition is None or receiver not in definition.parameters:
        return None
    if not separator or receiver not in {"self", "cls"}:
        return _ScopeBinding(unknown=True)
    owner = _structural_parent(scope)
    owner_definition = _definition_at(context, owner, line) if owner is not None else None
    if owner_definition is None or owner_definition.kind != "class":
        return _ScopeBinding(unknown=True)
    target_id = context.context_ids.get(f"{owner}.{member}")
    return _ScopeBinding(target_id=target_id, unknown=target_id is None)


def _structural_parent(context: str) -> str | None:
    return context.rpartition(".")[0] or None


def _definition_at(
    context: _ModuleContext,
    qualified_name: str,
    line: int,
) -> Definition | None:
    for definition in context.structure.definitions:
        if definition.qualified_name == qualified_name and _inside_definition(definition, line):
            return definition
    return None


def _inside_definition(definition: Definition | None, line: int) -> bool:
    return definition is None or definition.start_line <= line <= definition.end_line


def _context_id(context: _ModuleContext, qualified_name: str | None) -> str:
    if qualified_name is None:
        return context.module_id
    try:
        return context.context_ids[qualified_name]
    except KeyError as error:
        raise IndexBuildError(f"unknown source context: {qualified_name}") from error


def _module_name(path: str, *, src_is_package: bool) -> str:
    _validate_relative_path(path)
    parts = list(PurePosixPath(path).parts)
    if not src_is_package and len(parts) > 1 and parts[0] == "src" and parts[1] != "__init__.py":
        parts.pop(0)
    filename = parts[-1]
    if filename == "__init__.py" and len(parts) > 1:
        parts.pop()
    else:
        parts[-1] = filename.removesuffix(".py")
    return ".".join(parts)


def _import_bindings(
    module_name: str,
    source_path: str,
    imports: tuple[ImportEntry, ...],
) -> tuple[_ImportBinding, ...]:
    result: list[_ImportBinding] = []
    for imported in imports:
        resolved_target = _resolved_import_target(module_name, source_path, imported)
        visible = _visible_import_binding(imported)
        if resolved_target is None or visible is None:
            continue
        target = _import_binding_target(imported, resolved_target)
        scopes = (
            (imported.context, imported.conditional, False),
            *(
                (item.context, item.conditional, item.deferred)
                for item in imported.projected_binding_scopes
            ),
        )
        for scope, conditional, deferred in scopes:
            result.append(
                _ImportBinding(
                    scope,
                    visible,
                    target,
                    imported.line,
                    imported.column,
                    conditional,
                    deferred,
                )
            )
    return tuple(result)


def _store_bindings(bindings: tuple[StoreBinding, ...]) -> tuple[_StoreBinding, ...]:
    result: list[_StoreBinding] = []
    for binding in bindings:
        scopes = (
            (binding.context, binding.conditional, False),
            *(
                (item.context, item.conditional, item.deferred)
                for item in binding.projected_binding_scopes
            ),
        )
        for scope, conditional, deferred in scopes:
            result.append(
                _StoreBinding(
                    scope,
                    binding.name,
                    binding.line,
                    binding.column,
                    conditional,
                    binding.runtime,
                    deferred,
                )
            )
    return tuple(result)


def _resolved_import_target(
    module_name: str,
    source_path: str,
    imported: ImportEntry,
) -> str | None:
    if imported.level == 0:
        return import_target(imported)

    package = module_name.split(".")
    if PurePosixPath(source_path).name != "__init__.py":
        package.pop()
    upward = imported.level - 1
    if upward > len(package):
        return None
    if upward:
        package = package[:-upward]

    parts = [*package]
    if imported.module:
        parts.extend(imported.module.split("."))
    if imported.name and imported.name != "*":
        parts.append(imported.name)
    return ".".join(parts) or None


def _visible_import_binding(imported: ImportEntry) -> str | None:
    if imported.alias is not None:
        return imported.alias
    if imported.name is not None:
        return None if imported.name == "*" else imported.name
    if imported.module is None:
        return None
    return imported.module.split(".", 1)[0]


def _import_binding_target(imported: ImportEntry, resolved_target: str) -> str:
    if imported.alias is None and imported.name is None:
        return resolved_target.split(".", 1)[0]
    return resolved_target


def _imported_target(binding: _ImportBinding, target: str) -> str | None:
    if target == binding.visible:
        return binding.target
    if target.startswith(f"{binding.visible}."):
        return f"{binding.target}{target[len(binding.visible) :]}"
    return None


def _has_declaration(
    context: _ModuleContext,
    scope: str | None,
    line: int,
    name: str,
    kind: Literal["global", "nonlocal"],
) -> bool:
    definition = _definition_at(context, scope, line) if scope is not None else None
    return any(
        declaration.kind == kind
        and declaration.context == scope
        and declaration.name == name
        and definition is not None
        and definition.start_line <= declaration.line <= definition.end_line
        for declaration in context.structure.declarations
    )


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


def config_digest(config: ConfigData) -> str:
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
