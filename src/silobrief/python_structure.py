from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import Literal, TypeAlias

from silobrief.sources import SourceFile, SourceSnapshot

DefinitionKind: TypeAlias = Literal["class", "function"]


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


@dataclass(frozen=True, slots=True)
class ImportEntry:
    module: str | None
    name: str | None
    alias: str | None
    level: int
    context: str | None
    line: int
    column: int


@dataclass(frozen=True, slots=True)
class SymbolUse:
    context: str | None
    target: str
    line: int
    column: int


@dataclass(frozen=True, slots=True)
class ModuleStructure:
    path: str
    definitions: tuple[Definition, ...]
    imports: tuple[ImportEntry, ...]
    calls: tuple[SymbolUse, ...]
    references: tuple[SymbolUse, ...]


def extract_structures(snapshot: SourceSnapshot) -> tuple[ModuleStructure, ...]:
    return tuple(
        extract_module_structure(source)
        for source in sorted(snapshot.files, key=lambda candidate: candidate.path)
    )


def extract_module_structure(source: SourceFile) -> ModuleStructure:
    try:
        tree = ast.parse(source.content, filename=source.path, mode="exec")
    except SyntaxError as error:
        raise PythonParseError(
            path=source.path,
            line=error.lineno,
            column=error.offset,
            reason=error.msg,
        ) from error

    visitor = _StructureVisitor()
    visitor.visit(tree)
    return ModuleStructure(
        path=source.path,
        definitions=tuple(visitor.definitions),
        imports=tuple(visitor.imports),
        calls=tuple(visitor.calls),
        references=tuple(visitor.references),
    )


class _StructureVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.definitions: list[Definition] = []
        self.imports: list[ImportEntry] = []
        self.calls: list[SymbolUse] = []
        self.references: list[SymbolUse] = []
        self._contexts: list[str] = []

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
                )
            )

    def visit_Call(self, node: ast.Call) -> None:
        target = _dotted_name(node.func)
        if target is None:
            self.visit(node.func)
        else:
            line, column = _location(node)
            self.calls.append(SymbolUse(self._context, target, line, column))

        for argument in node.args:
            self.visit(argument)
        for keyword in node.keywords:
            self.visit(keyword.value)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if isinstance(node.ctx, ast.Load):
            target = _dotted_name(node)
            if target is not None:
                line, column = _location(node)
                self.references.append(SymbolUse(self._context, target, line, column))
                return
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, ast.Load):
            line, column = _location(node)
            self.references.append(SymbolUse(self._context, node.id, line, column))

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
            )
        )
        self._visit_definition_header(node)
        self._contexts.append(qualified_name)
        try:
            for statement in node.body:
                self.visit(statement)
        finally:
            self._contexts.pop()

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

    @property
    def _context(self) -> str | None:
        return self._contexts[-1] if self._contexts else None


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


def _location(node: ast.stmt | ast.expr) -> tuple[int, int]:
    return node.lineno, node.col_offset + 1
