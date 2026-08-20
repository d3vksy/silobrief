from __future__ import annotations

import ast
import io
import symtable
import tokenize
from dataclasses import dataclass
from typing import Literal, TypeAlias

from silobrief.sources import SourceFile, SourceSnapshot

DefinitionKind: TypeAlias = Literal["class", "function"]
DeclarationKind: TypeAlias = Literal["global", "nonlocal"]


class PythonParseError(Exception):
    path: str
    line: int | None
    column: int | None
    reason: str

    def __init__(
        self,
        path: str,
        line: int | None,
        column: int | None,
        reason: str,
    ) -> None:
        self.path = path
        self.line = line
        self.column = column
        self.reason = reason
        location = ":".join(
            (
                path,
                str(line) if line is not None else "?",
                str(column) if column is not None else "?",
            )
        )
        super().__init__(f"cannot parse {location}: {reason}")


@dataclass(frozen=True, slots=True)
class Definition:
    kind: DefinitionKind
    name: str
    qualified_name: str
    is_async: bool
    line: int
    column: int
    start_line: int
    end_line: int
    parameters: tuple[str, ...] = ()
    conditional: bool = False


@dataclass(frozen=True, slots=True)
class ImportBindingScope:
    context: str | None
    conditional: bool = False
    deferred: bool = False


@dataclass(frozen=True, slots=True)
class ImportEntry:
    module: str | None
    name: str | None
    alias: str | None
    level: int
    context: str | None
    line: int
    column: int
    conditional: bool = False
    projected_binding_scopes: tuple[ImportBindingScope, ...] = ()


@dataclass(frozen=True, slots=True)
class StoreBinding:
    name: str
    context: str | None
    line: int
    column: int
    conditional: bool = False
    runtime: bool = True
    projected_binding_scopes: tuple[ImportBindingScope, ...] = ()


@dataclass(frozen=True, slots=True)
class SymbolUse:
    context: str | None
    target: str
    line: int
    column: int
    skip_class_scope: bool = False
    synthetic_local: bool = False
    lookup_limit: tuple[int, int] | None = None
    disclosure_context: str | None = None
    boundary_only: bool = False


@dataclass(frozen=True, slots=True)
class ScopeDeclaration:
    kind: DeclarationKind
    name: str
    context: str | None
    line: int
    column: int


@dataclass(frozen=True, slots=True)
class ModuleStructure:
    path: str
    definitions: tuple[Definition, ...]
    imports: tuple[ImportEntry, ...]
    calls: tuple[SymbolUse, ...]
    references: tuple[SymbolUse, ...]
    declarations: tuple[ScopeDeclaration, ...]
    store_bindings: tuple[StoreBinding, ...] = ()


def extract_structures(snapshot: SourceSnapshot) -> tuple[ModuleStructure, ...]:
    return tuple(
        extract_module_structure(source)
        for source in sorted(snapshot.files, key=lambda candidate: candidate.path)
    )


def extract_module_structure(source: SourceFile) -> ModuleStructure:
    try:
        tree = ast.parse(source.content, filename=source.path, mode="exec", type_comments=True)
        encoding, _ = tokenize.detect_encoding(io.BytesIO(source.content).readline)
        symbols = _scope_symbol_table(source.content.decode(encoding), source.path)
    except SyntaxError as error:
        raise PythonParseError(
            path=source.path,
            line=error.lineno,
            column=error.offset,
            reason=error.msg,
        ) from error

    visitor = _StructureVisitor(symbols)
    visitor.visit(tree)
    return ModuleStructure(
        path=source.path,
        definitions=tuple(visitor.definitions),
        imports=tuple(visitor.imports),
        calls=tuple(visitor.calls),
        references=tuple(visitor.references),
        declarations=tuple(visitor.declarations),
        store_bindings=tuple(visitor.store_bindings),
    )


def _scope_symbol_table(source: str, path: str) -> symtable.SymbolTable:
    try:
        return symtable.symtable(source, path, "exec")
    except SyntaxError as original_error:
        try:
            compile(
                source,
                path,
                "exec",
                flags=ast.PyCF_ALLOW_TOP_LEVEL_AWAIT,
                dont_inherit=True,
            )
        except SyntaxError:
            raise original_error from None
        try:
            return symtable.symtable(_without_async_keywords(source), path, "exec")
        except (RuntimeError, SyntaxError):
            raise original_error from None


def _without_async_keywords(source: str) -> str:
    lines = list(io.StringIO(source))
    edits: dict[int, list[tuple[int, int, str]]] = {}
    tokens = tuple(tokenize.generate_tokens(io.StringIO(source).readline))
    for index, token in enumerate(tokens):
        if token.type != tokenize.NAME or token.string not in {"async", "await"}:
            continue
        replacement = "+    "
        if token.string == "async":
            following = next(
                candidate
                for candidate in tokens[index + 1 :]
                if candidate.type
                not in {
                    tokenize.COMMENT,
                    tokenize.DEDENT,
                    tokenize.INDENT,
                    tokenize.NEWLINE,
                    tokenize.NL,
                }
            )
            if following.string not in {"def", "for", "with"}:
                raise RuntimeError("unexpected async syntax while building symbol table")
            replacement = following.string.ljust(len(token.string))
            edits.setdefault(following.start[0] - 1, []).append(
                (following.start[1], following.end[1], " " * len(following.string))
            )
        edits.setdefault(token.start[0] - 1, []).append((token.start[1], token.end[1], replacement))
    for line, ranges in edits.items():
        for start, end, replacement in sorted(ranges, reverse=True):
            lines[line] = f"{lines[line][:start]}{replacement}{lines[line][end:]}"
    rewritten = "".join(lines)
    if len(rewritten) != len(source):
        raise RuntimeError("symbol-table rewrite changed source positions")
    return rewritten


class _StructureVisitor(ast.NodeVisitor):
    def __init__(self, symbols: symtable.SymbolTable) -> None:
        self.definitions: list[Definition] = []
        self.imports: list[ImportEntry] = []
        self.calls: list[SymbolUse] = []
        self.references: list[SymbolUse] = []
        self.declarations: list[ScopeDeclaration] = []
        self.store_bindings: list[StoreBinding] = []
        self._contexts: list[str] = []
        self._context_kinds: list[DefinitionKind] = []
        self._context_conditionals: list[bool] = []
        self._scope_declarations: list[dict[str, DeclarationKind]] = []
        self._symbol_tables = [symbols]
        self._conditional_depth = 0
        self._synthetic_scopes: list[set[str]] = []
        self._suppress_store_bindings = 0
        self._store_position_overrides: list[tuple[int, int]] = []
        self._lookup_limit: tuple[int, int] | None = None
        self._disclosure_context: str | None = None
        self._annotation_depth = 0
        self._boundary_only_uses = 0
        self._deferred_annotation_stack: list[str] = []

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._visit_definition(node, "class", is_async=False)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_definition(node, "function", is_async=False)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_definition(node, "function", is_async=True)

    def visit_Import(self, node: ast.Import) -> None:
        line, column = _location(node)
        for imported in node.names:
            self.imports.append(
                ImportEntry(
                    module=imported.name,
                    name=None,
                    alias=imported.asname,
                    level=0,
                    context=self._context,
                    line=line,
                    column=column,
                    conditional=self._conditional_depth > 0,
                    projected_binding_scopes=self._projected_binding_scopes(
                        imported.asname or imported.name.split(".", 1)[0]
                    ),
                )
            )

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        line, column = _location(node)
        for imported in node.names:
            self.imports.append(
                ImportEntry(
                    module=node.module,
                    name=imported.name,
                    alias=imported.asname,
                    level=node.level,
                    context=self._context,
                    line=line,
                    column=column,
                    conditional=self._conditional_depth > 0,
                    projected_binding_scopes=self._projected_binding_scopes(
                        imported.asname or imported.name
                    ),
                )
            )

    def visit_Call(self, node: ast.Call) -> None:
        target = _dotted_name(node.func)
        if target is None:
            self.visit(node.func)
        else:
            line, column = _location(node)
            self.calls.append(self._symbol_use(target, line, column))

        for argument in node.args:
            self.visit(argument)
        for keyword in node.keywords:
            self.visit(keyword.value)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if isinstance(node.ctx, ast.Load):
            target = _dotted_name(node)
            if target is not None:
                line, column = _location(node)
                self.references.append(self._symbol_use(target, line, column))
                return
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, ast.Load):
            line, column = _location(node)
            self.references.append(self._symbol_use(node.id, line, column))

    def visit_Constant(self, node: ast.Constant) -> None:
        if self._annotation_depth and isinstance(node.value, str):
            self._visit_deferred_annotation(node.value, node, mode="eval")

    def visit_arg(self, node: ast.arg) -> None:
        if node.annotation is not None:
            self._visit_annotation(node.annotation)
        if node.type_comment is not None:
            self._visit_deferred_annotation(node.type_comment, node, mode="eval")

    def visit_Assign(self, node: ast.Assign) -> None:
        self.visit(node.value)
        for target in node.targets:
            self._visit_store_target(target, _end_location(node))
        self._record_store_bindings(
            set().union(*(_bound_names(target) for target in node.targets)),
            _end_location(node),
        )

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if node.value is not None:
            self.visit(node.value)
        self._visit_store_target(node.target, _end_location(node))
        self.visit(node.annotation)
        self._record_store_bindings(
            _bound_names(node.target),
            _end_location(node),
            runtime=node.value is not None,
        )

    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        self.visit(node.target)
        self.visit(node.value)
        self._record_store_bindings(_bound_names(node.target), _end_location(node))

    def visit_NamedExpr(self, node: ast.NamedExpr) -> None:
        self.visit(node.value)
        self.visit(node.target)
        self._record_store_bindings(
            _bound_names(node.target),
            _end_location(node),
            conditional=bool(self._synthetic_scopes),
        )

    def visit_BoolOp(self, node: ast.BoolOp) -> None:
        first, *remaining = node.values
        self.visit(first)
        self._conditional_depth += 1
        try:
            for value in remaining:
                self.visit(value)
        finally:
            self._conditional_depth -= 1

    def visit_IfExp(self, node: ast.IfExp) -> None:
        self.visit(node.test)
        self._conditional_depth += 1
        try:
            self.visit(node.body)
            self.visit(node.orelse)
        finally:
            self._conditional_depth -= 1

    def visit_Compare(self, node: ast.Compare) -> None:
        self.visit(node.left)
        first, *remaining = node.comparators
        self.visit(first)
        self._conditional_depth += 1
        try:
            for comparator in remaining:
                self.visit(comparator)
        finally:
            self._conditional_depth -= 1

    def visit_Assert(self, node: ast.Assert) -> None:
        self._conditional_depth += 1
        try:
            self.visit(node.test)
            if node.msg is not None:
                self.visit(node.msg)
        finally:
            self._conditional_depth -= 1

    def visit_Lambda(self, node: ast.Lambda) -> None:
        for default in (*node.args.defaults, *node.args.kw_defaults):
            if default is not None:
                self.visit(default)
        names = set(_argument_names(node.args))
        names.update(_walrus_bound_names(node.body))
        self._visit_synthetic(node.body, names, suppress_store_bindings=True)

    def visit_ListComp(self, node: ast.ListComp) -> None:
        self._visit_comprehension(node.generators, (node.elt,))

    def visit_SetComp(self, node: ast.SetComp) -> None:
        self._visit_comprehension(node.generators, (node.elt,))

    def visit_GeneratorExp(self, node: ast.GeneratorExp) -> None:
        self._visit_comprehension(node.generators, (node.elt,))

    def visit_DictComp(self, node: ast.DictComp) -> None:
        self._visit_comprehension(node.generators, (node.key, node.value))

    def visit_If(self, node: ast.If) -> None:
        self._visit_conditional(node)

    def visit_For(self, node: ast.For) -> None:
        self._visit_for(node)

    def visit_AsyncFor(self, node: ast.AsyncFor) -> None:
        self._visit_for(node)

    def visit_While(self, node: ast.While) -> None:
        self._visit_conditional(node)

    def visit_Try(self, node: ast.Try) -> None:
        self._visit_conditional(node)

    def visit_TryStar(self, node: ast.AST) -> None:
        self._visit_conditional(node)

    def visit_Match(self, node: ast.Match) -> None:
        self._conditional_depth += 1
        try:
            self.visit(node.subject)
            for case in node.cases:
                self.visit(case.pattern)
                self._record_store_bindings(
                    _match_bound_names(case.pattern),
                    _end_location(case.pattern),
                )
                if case.guard is not None:
                    self.visit(case.guard)
                for statement in case.body:
                    self.visit(statement)
        finally:
            self._conditional_depth -= 1

    def visit_With(self, node: ast.With) -> None:
        self._visit_with(node)

    def visit_AsyncWith(self, node: ast.AsyncWith) -> None:
        self._visit_with(node)

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        if node.type is not None:
            self.visit(node.type)
        if node.name is not None:
            position = _end_location(node.type) if node.type is not None else _location(node)
            self._record_store_bindings({node.name}, position)
        for statement in node.body:
            self.visit(statement)

    def visit_Global(self, node: ast.Global) -> None:
        self._record_declarations("global", node)

    def visit_Nonlocal(self, node: ast.Nonlocal) -> None:
        self._record_declarations("nonlocal", node)

    def _visit_definition(
        self,
        node: ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef,
        kind: DefinitionKind,
        *,
        is_async: bool,
    ) -> None:
        qualified_name = f"{self._context}.{node.name}" if self._context else node.name
        line, column = _location(node)
        start_line = min((node.lineno, *(item.lineno for item in node.decorator_list)))
        end_line = node.end_lineno if node.end_lineno is not None else node.lineno
        self.definitions.append(
            Definition(
                kind,
                node.name,
                qualified_name,
                is_async,
                line,
                column,
                start_line,
                end_line,
                _function_parameters(node),
                self._conditional_depth > 0,
            )
        )
        previous_limit = self._lookup_limit
        previous_disclosure_context = self._disclosure_context
        self._lookup_limit = (line, column)
        self._disclosure_context = qualified_name
        try:
            self._visit_definition_header(node)
        finally:
            self._lookup_limit = previous_limit
            self._disclosure_context = previous_disclosure_context
        self._contexts.append(qualified_name)
        self._context_kinds.append(kind)
        self._context_conditionals.append(self._conditional_depth > 0)
        self._scope_declarations.append({})
        self._symbol_tables.append(_child_symbol_table(self._symbol_tables[-1], node, kind))
        previous_conditional_depth = self._conditional_depth
        self._conditional_depth = 0
        try:
            for statement in node.body:
                self.visit(statement)
        finally:
            self._conditional_depth = previous_conditional_depth
            self._scope_declarations.pop()
            self._context_conditionals.pop()
            self._context_kinds.pop()
            self._contexts.pop()
            self._symbol_tables.pop()

    def _visit_definition_header(
        self, node: ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef
    ) -> None:
        for field, value in ast.iter_fields(node):
            if field == "body":
                continue
            if isinstance(value, ast.AST):
                if field == "returns":
                    self._visit_annotation(value)
                else:
                    self.visit(value)
            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, ast.AST):
                        if field == "type_params":
                            self._visit_annotation(item)
                        else:
                            self.visit(item)
            elif field == "type_comment" and isinstance(value, str):
                self._visit_deferred_annotation(value, node, mode="func_type")

    def _visit_annotation(self, node: ast.AST) -> None:
        self._annotation_depth += 1
        try:
            self.visit(node)
        finally:
            self._annotation_depth -= 1

    def _visit_deferred_annotation(
        self,
        value: str,
        origin: ast.AST,
        *,
        mode: Literal["eval", "func_type"],
    ) -> None:
        if value in self._deferred_annotation_stack:
            return
        try:
            parsed = ast.parse(value, filename="<annotation>", mode=mode)
        except SyntaxError:
            return
        ast.increment_lineno(parsed, getattr(origin, "lineno", 1) - 1)
        self._deferred_annotation_stack.append(value)
        self._annotation_depth += 1
        self._boundary_only_uses += 1
        self._suppress_store_bindings += 1
        try:
            self.visit(parsed)
        finally:
            self._suppress_store_bindings -= 1
            self._boundary_only_uses -= 1
            self._annotation_depth -= 1
            self._deferred_annotation_stack.pop()

    def _record_declarations(
        self,
        kind: DeclarationKind,
        node: ast.Global | ast.Nonlocal,
    ) -> None:
        line, column = _location(node)
        self.declarations.extend(
            ScopeDeclaration(kind, name, self._context, line, column) for name in node.names
        )
        if self._scope_declarations:
            self._scope_declarations[-1].update(dict.fromkeys(node.names, kind))

    def _projected_binding_scopes(self, name: str) -> tuple[ImportBindingScope, ...]:
        if not self._context_kinds:
            return ()
        declaration = self._scope_declarations[-1].get(name)
        if declaration is None:
            return ()

        source_kind = self._context_kinds[-1]
        deferred = source_kind == "function"
        conditional = self._conditional_depth > 0
        conditional = conditional or (
            self._context_conditionals[-1] if source_kind == "class" else True
        )
        if declaration == "global":
            for kind, definition_conditional in zip(
                self._context_kinds[:-1], self._context_conditionals[:-1], strict=True
            ):
                if kind == "function":
                    conditional = deferred = True
                conditional = conditional or definition_conditional
            return (ImportBindingScope(None, conditional, deferred),)

        for index in range(len(self._contexts) - 2, -1, -1):
            kind = self._context_kinds[index]
            if kind == "function":
                try:
                    owns_name = self._symbol_tables[index + 1].lookup(name).is_local()
                except KeyError:
                    owns_name = False
                if owns_name:
                    return (ImportBindingScope(self._contexts[index], conditional, deferred),)
                conditional = deferred = True
            else:
                conditional = conditional or self._context_conditionals[index]
        return ()

    def _symbol_use(self, target: str, line: int, column: int) -> SymbolUse:
        root = target.split(".", 1)[0]
        return SymbolUse(
            self._context,
            target,
            line,
            column,
            skip_class_scope=bool(self._synthetic_scopes),
            synthetic_local=any(root in scope for scope in reversed(self._synthetic_scopes)),
            lookup_limit=self._lookup_limit,
            disclosure_context=self._disclosure_context,
            boundary_only=bool(self._boundary_only_uses),
        )

    def _visit_synthetic(
        self,
        node: ast.AST,
        names: set[str],
        *,
        suppress_store_bindings: bool = False,
    ) -> None:
        self._synthetic_scopes.append(names)
        self._suppress_store_bindings += suppress_store_bindings
        try:
            self.visit(node)
        finally:
            self._suppress_store_bindings -= suppress_store_bindings
            self._synthetic_scopes.pop()

    def _visit_comprehension(
        self,
        generators: list[ast.comprehension],
        results: tuple[ast.expr, ...],
    ) -> None:
        first, *remaining = generators
        self.visit(first.iter)
        names = set().union(*(_bound_names(generator.target) for generator in generators))
        self._synthetic_scopes.append(names)
        try:
            self.visit(first.target)
            for condition in first.ifs:
                self.visit(condition)
            for generator in remaining:
                self.visit(generator.iter)
                self.visit(generator.target)
                for condition in generator.ifs:
                    self.visit(condition)
            for result in results:
                self.visit(result)
        finally:
            self._synthetic_scopes.pop()

    def _visit_for(self, node: ast.For | ast.AsyncFor) -> None:
        self._conditional_depth += 1
        try:
            self.visit(node.iter)
            self._visit_store_target(node.target, _end_location(node.iter))
            self._record_store_bindings(_bound_names(node.target), _end_location(node.iter))
            for statement in (*node.body, *node.orelse):
                self.visit(statement)
        finally:
            self._conditional_depth -= 1

    def _visit_with(self, node: ast.With | ast.AsyncWith) -> None:
        self._conditional_depth += 1
        try:
            for item in node.items:
                self.visit(item.context_expr)
                if item.optional_vars is not None:
                    self._visit_store_target(item.optional_vars, _end_location(item.optional_vars))
                    self._record_store_bindings(
                        _bound_names(item.optional_vars),
                        _end_location(item.optional_vars),
                    )
            for statement in node.body:
                self.visit(statement)
        finally:
            self._conditional_depth -= 1

    def _record_store_bindings(
        self,
        names: set[str],
        position: tuple[int, int],
        *,
        conditional: bool = False,
        runtime: bool = True,
    ) -> None:
        if self._suppress_store_bindings:
            return
        if self._store_position_overrides:
            position = self._store_position_overrides[-1]
        line, column = position
        for name in sorted(names):
            self.store_bindings.append(
                StoreBinding(
                    name,
                    self._context,
                    line,
                    column,
                    conditional=self._conditional_depth > 0 or conditional,
                    runtime=runtime,
                    projected_binding_scopes=self._projected_binding_scopes(name),
                )
            )

    def _visit_store_target(self, node: ast.expr, position: tuple[int, int]) -> None:
        self._store_position_overrides.append(position)
        try:
            self.visit(node)
        finally:
            self._store_position_overrides.pop()

    def _visit_conditional(self, node: ast.AST) -> None:
        self._conditional_depth += 1
        try:
            self.generic_visit(node)
        finally:
            self._conditional_depth -= 1

    @property
    def _context(self) -> str | None:
        return self._contexts[-1] if self._contexts else None


def _child_symbol_table(
    parent: symtable.SymbolTable,
    node: ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef,
    kind: DefinitionKind,
) -> symtable.SymbolTable:
    for child in parent.get_children():
        if child.get_name() == node.name and child.get_lineno() == node.lineno:
            if child.get_type() == kind:
                return child
            try:
                return _child_symbol_table(child, node, kind)
            except RuntimeError:
                pass
    raise RuntimeError(f"missing symbol table for {kind} {node.name} at line {node.lineno}")


def _dotted_name(node: ast.expr) -> str | None:
    parts: list[str] = []
    current = node
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if not isinstance(current, ast.Name):
        return None
    parts.append(current.id)
    parts.reverse()
    return ".".join(parts)


def _function_parameters(
    node: ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef,
) -> tuple[str, ...]:
    return () if isinstance(node, ast.ClassDef) else _argument_names(node.args)


def _argument_names(arguments: ast.arguments) -> tuple[str, ...]:
    names = [argument.arg for argument in (*arguments.posonlyargs, *arguments.args)]
    if arguments.vararg is not None:
        names.append(arguments.vararg.arg)
    names.extend(argument.arg for argument in arguments.kwonlyargs)
    if arguments.kwarg is not None:
        names.append(arguments.kwarg.arg)
    return tuple(names)


def _bound_names(node: ast.expr) -> set[str]:
    if isinstance(node, ast.Name):
        return {node.id}
    if isinstance(node, (ast.List, ast.Tuple)):
        return set().union(*(_bound_names(item) for item in node.elts))
    if isinstance(node, ast.Starred):
        return _bound_names(node.value)
    return set()


def _match_bound_names(node: ast.pattern) -> set[str]:
    if isinstance(node, ast.MatchAs):
        names = _match_bound_names(node.pattern) if node.pattern is not None else set()
        if node.name is not None:
            names.add(node.name)
        return names
    if isinstance(node, ast.MatchStar):
        return {node.name} if node.name is not None else set()
    if isinstance(node, ast.MatchSequence):
        return set().union(*(_match_bound_names(item) for item in node.patterns))
    if isinstance(node, ast.MatchMapping):
        names = set().union(*(_match_bound_names(item) for item in node.patterns))
        if node.rest is not None:
            names.add(node.rest)
        return names
    if isinstance(node, ast.MatchClass):
        return set().union(
            *(_match_bound_names(item) for item in (*node.patterns, *node.kwd_patterns))
        )
    if isinstance(node, ast.MatchOr):
        return set().union(*(_match_bound_names(item) for item in node.patterns))
    return set()


def _walrus_bound_names(node: ast.AST) -> set[str]:
    names: set[str] = set()

    def collect(current: ast.AST) -> None:
        if isinstance(current, ast.Lambda):
            for default in (*current.args.defaults, *current.args.kw_defaults):
                if default is not None:
                    collect(default)
            return
        if isinstance(current, ast.NamedExpr):
            names.update(_bound_names(current.target))
        for child in ast.iter_child_nodes(current):
            collect(child)

    collect(node)
    return names


def _location(node: ast.stmt | ast.expr | ast.pattern | ast.ExceptHandler) -> tuple[int, int]:
    return node.lineno, node.col_offset + 1


def _end_location(node: ast.stmt | ast.expr | ast.pattern) -> tuple[int, int]:
    line = node.end_lineno if node.end_lineno is not None else node.lineno
    column = node.end_col_offset if node.end_col_offset is not None else node.col_offset
    return line, column + 1
