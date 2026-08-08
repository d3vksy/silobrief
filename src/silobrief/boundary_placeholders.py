from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath

from silobrief.python_structure import ImportEntry
from silobrief.state import BoundaryData


@dataclass(frozen=True, slots=True)
class BoundaryPlaceholder:
    alias: str
    description: str


@dataclass(frozen=True, slots=True)
class _BoundaryRule:
    modules: tuple[str, ...]
    placeholder: BoundaryPlaceholder


class BoundaryMatcher:
    def __init__(
        self,
        source_path: str,
        imports: tuple[ImportEntry, ...],
        boundaries: tuple[BoundaryData, ...],
    ) -> None:
        self._source_path = source_path
        self._rules = tuple(
            sorted(
                (_boundary_rule(boundary) for boundary in boundaries),
                key=lambda rule: (
                    -(rule.modules[0].count(".") + 1 if rule.modules[0] else 0),
                    rule.modules,
                    rule.placeholder.alias,
                    rule.placeholder.description,
                ),
            )
        )
        bindings: dict[str | None, dict[str, str]] = {}
        for imported in imports:
            resolved = _resolved_import_target(source_path, imported)
            visible = _visible_binding(imported)
            if resolved is not None and visible is not None:
                bindings.setdefault(imported.context, {})[visible] = resolved
        self._bindings = {
            context: tuple(
                sorted(values.items(), key=lambda item: (-len(item[0].split(".")), item[0]))
            )
            for context, values in bindings.items()
        }

    def match_import(self, imported: ImportEntry) -> BoundaryPlaceholder | None:
        resolved = _resolved_import_target(self._source_path, imported)
        return self._match_module(resolved)

    def match_use(
        self,
        target: str,
        context: str | None,
    ) -> BoundaryPlaceholder | None:
        direct = self._match_module(target)
        if direct is not None:
            return direct
        for visible, origin in self._visible_origins(context):
            if target == visible:
                return self._match_module(origin)
            if target.startswith(f"{visible}."):
                suffix = target[len(visible) :]
                return self._match_module(f"{origin}{suffix}")
        return None

    def _visible_origins(self, context: str | None) -> tuple[tuple[str, str], ...]:
        contexts: list[str | None] = []
        current = context
        while current is not None:
            contexts.append(current)
            current, separator, _ = current.rpartition(".")
            if not separator:
                current = None
        contexts.append(None)

        result: list[tuple[str, str]] = []
        seen: set[str] = set()
        for candidate in contexts:
            for visible, origin in self._bindings.get(candidate, ()):
                if visible not in seen:
                    seen.add(visible)
                    result.append((visible, origin))
        return tuple(result)

    def _match_module(self, module: str | None) -> BoundaryPlaceholder | None:
        if module is None:
            return None
        for rule in self._rules:
            for candidate in rule.modules:
                if not candidate or module == candidate or module.startswith(f"{candidate}."):
                    return rule.placeholder
        return None


def import_target(imported: ImportEntry) -> str:
    prefix = "." * imported.level
    module = imported.module or ""
    base = f"{prefix}{module}"
    if imported.name is None:
        return base
    separator = "" if not base or base.endswith(".") else "."
    return f"{base}{separator}{imported.name}"


def _boundary_rule(boundary: BoundaryData) -> _BoundaryRule:
    parts = list(PurePosixPath(boundary["path"]).parts)
    if boundary["path"] == ".":
        module = ""
    elif parts[-1] == "__init__.py":
        module = ".".join(parts[:-1])
    elif parts[-1].endswith(".py"):
        parts[-1] = parts[-1][:-3]
        module = ".".join(parts)
    else:
        module = ".".join(parts)
    return _BoundaryRule(
        modules=_module_candidates(module),
        placeholder=BoundaryPlaceholder(
            alias=boundary["alias"],
            description=boundary["description"],
        ),
    )


def _module_candidates(module: str) -> tuple[str, ...]:
    if not module:
        return ("",)
    # Stored paths are project-relative, while absolute imports start at a package root.
    parts = module.split(".")
    return tuple(".".join(parts[index:]) for index in range(len(parts)))


def _resolved_import_target(source_path: str, imported: ImportEntry) -> str | None:
    if imported.level == 0:
        return import_target(imported)

    path_parts = list(PurePosixPath(source_path).parts)
    path_parts.pop()
    package = path_parts
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


def _visible_binding(imported: ImportEntry) -> str | None:
    if imported.alias is not None:
        return imported.alias
    if imported.name is not None:
        return None if imported.name == "*" else imported.name
    return imported.module
