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
class SymbolUse:
    context: str | None
    target: str
    line: int
    column: int
    skip_class_scope: bool = False
    synthetic_local: bool = False
    lookup_limit: tuple[int, int] | None = None


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


def extract_structures(snapshot: SourceSnapshot) -> tuple[ModuleStructure, ...]:
    return tuple(
        extract_module_structure(source)
        for source in sorted(snapshot.files, key=lambda candidate: candidate.path)
    )


def extract_module_structure(source: SourceFile) -> ModuleStructure:
    try:
        tree = ast.parse(source.content, filename=source.path, mode="exec")
        encoding, _ = tokenize.detect_encoding(io.BytesIO(source.content).readline)
        symbols = symtable.symtable(source.content.decode(encoding), source.path, "exec")
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
    )


class _StructureVisitor(ast.NodeVisitor):
    def __init__(self, symbols: symtable.SymbolTable) -> None:
        self.definitions: list[Definition] = []
        self.imports: list[ImportEntry] = []
        self.calls: list[SymbolUse] = []
        self.references: list[SymbolUse] = []
        self.declarations: list[ScopeDeclaration] = []
        self._contexts: list[str] = []
        self._context_kinds: list[DefinitionKind] = []
        self._context_conditionals: list[bool] = []
        self._scope_declarations: list[dict[str, DeclarationKind]] = []
        self._symbol_tables = [symbols]
        self._conditional_depth = 0
        self._synthetic_scopes: list[set[str]] = []
        self._lookup_limit: tuple[int, int] | None = None

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
                    projected_binding_scopes=self._projected_import_scopes(
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
                    projected_binding_scopes=self._projected_import_scopes(
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

    def visit_Lambda(self, node: ast.Lambda) -> None:
        for default in (*node.args.defaults, *node.args.kw_defaults):
            if default is not None:
                self.visit(default)
        self._visit_synthetic(node.body, set(_argument_names(node.args)))

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
        self._visit_conditional(node)

    def visit_AsyncFor(self, node: ast.AsyncFor) -> None:
        self._visit_conditional(node)

    def visit_While(self, node: ast.While) -> None:
        self._visit_conditional(node)

    def visit_Try(self, node: ast.Try) -> None:
        self._visit_conditional(node)

    def visit_TryStar(self, node: ast.AST) -> None:
        self._visit_conditional(node)

    def visit_Match(self, node: ast.Match) -> None:
        self._visit_conditional(node)

    def visit_With(self, node: ast.With) -> None:
        self._visit_conditional(node)

    def visit_AsyncWith(self, node: ast.AsyncWith) -> None:
        self._visit_conditional(node)

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
        self._lookup_limit = (line, column)
        try:
            self._visit_definition_header(node)
        finally:
            self._lookup_limit = previous_limit
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
                self.visit(value)
            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, ast.AST):
                        self.visit(item)

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

    def _projected_import_scopes(self, name: str) -> tuple[ImportBindingScope, ...]:
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
        )

    def _visit_synthetic(self, node: ast.AST, names: set[str]) -> None:
        self._synthetic_scopes.append(names)
        try:
            self.visit(node)
        finally:
            self._synthetic_scopes.pop()

    def _visit_comprehension(
        self,
        generators: list[ast.comprehension],
        results: tuple[ast.expr, ...],
    ) -> None:
        first, *remaining = generators
        self.visit(first.iter)
        names = _bound_names(first.target)
        self._synthetic_scopes.append(names)
        try:
            self.visit(first.target)
            for condition in first.ifs:
                self.visit(condition)
            for generator in remaining:
                self.visit(generator.iter)
                names.update(_bound_names(generator.target))
                self.visit(generator.target)
                for condition in generator.ifs:
                    self.visit(condition)
            for result in results:
                self.visit(result)
        finally:
            self._synthetic_scopes.pop()

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


def _location(node: ast.stmt | ast.expr) -> tuple[int, int]:
    return node.lineno, node.col_offset + 1
