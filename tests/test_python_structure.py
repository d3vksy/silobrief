from __future__ import annotations

import hashlib
import sys
import unittest
from unittest import mock

from silobrief.python_structure import (
    Definition,
    ImportBindingScope,
    ImportEntry,
    PythonParseError,
    ScopeDeclaration,
    SymbolUse,
    extract_structures,
)
from silobrief.sources import SourceFile, SourceSnapshot


def source_file(path: str, content: bytes) -> SourceFile:
    return SourceFile(
        path=path,
        content=content,
        sha256=hashlib.sha256(content).hexdigest(),
    )


def source_snapshot(*files: SourceFile) -> SourceSnapshot:
    return SourceSnapshot(files=files, warnings=(), digest="test-snapshot")


class PythonStructureTests(unittest.TestCase):
    def test_extracts_nested_classes_and_sync_and_async_functions(self) -> None:
        source = source_file(
            "package/service.py",
            (
                b"class Outer:\n"
                b"    class Inner:\n"
                b"        pass\n"
                b"    def method(self):\n"
                b"        pass\n"
                b"    async def fetch(self):\n"
                b"        pass\n"
                b"def top():\n"
                b"    def nested():\n"
                b"        pass\n"
            ),
        )

        (module,) = extract_structures(source_snapshot(source))

        self.assertEqual(module.path, "package/service.py")
        self.assertEqual(
            module.definitions,
            (
                Definition("class", "Outer", "Outer", False, 1, 1, 1, 7),
                Definition("class", "Inner", "Outer.Inner", False, 2, 5, 2, 3),
                Definition(
                    "function",
                    "method",
                    "Outer.method",
                    False,
                    4,
                    5,
                    4,
                    5,
                    ("self",),
                ),
                Definition(
                    "function",
                    "fetch",
                    "Outer.fetch",
                    True,
                    6,
                    5,
                    6,
                    7,
                    ("self",),
                ),
                Definition("function", "top", "top", False, 8, 1, 8, 10),
                Definition("function", "nested", "top.nested", False, 9, 5, 9, 10),
            ),
        )
        self.assertEqual(module.imports, ())
        self.assertEqual(module.calls, ())
        self.assertEqual(module.references, ())

    @unittest.skipIf(sys.version_info < (3, 12), "PEP 695 requires Python 3.12")
    def test_follows_type_parameter_symbol_tables_to_generic_definitions(self) -> None:
        source = source_file(
            "generics.py",
            (
                b"class Box[T]:\n"
                b"    import package\n"
                b"    def transform[U](self, value: U) -> T:\n"
                b"        import helper\n"
                b"        return value\n"
                b"def identity[T](value: T) -> T:\n"
                b"    return value\n"
            ),
        )

        (module,) = extract_structures(source_snapshot(source))

        self.assertEqual(
            tuple(item.qualified_name for item in module.definitions),
            ("Box", "Box.transform", "identity"),
        )
        self.assertEqual(
            tuple(item.context for item in module.imports),
            ("Box", "Box.transform"),
        )

    def test_accepts_top_level_async_syntax_without_losing_scope_owners(self) -> None:
        source = source_file(
            "pyodide_runner.py",
            (
                b"async def main():\n"
                b"    await inside()\n"
                b"def outer():\n"
                b"    selected = None\n"
                b"    def middle():\n"
                b"        class Configure:\n"
                b"            nonlocal selected\n"
                b"            import package.client as selected\n"
                b"        return Configure\n"
                b"    return middle\n"
                b"await main()\n"
                b"async for item in items:\n"
                b"    consume(item)\n"
                b"async with manager():\n"
                b"    consume(resource)\n"
                b"values = [item async for item in items]\n"
                b"async \\\n"
                b"def continued():\n"
                b"    pass\n"
                b"await\f continued()\n"
                b"async\fdef formfeed():\n"
                b"    pass\n"
            ),
        )

        (module,) = extract_structures(source_snapshot(source))
        selected = next(item for item in module.imports if item.alias == "selected")

        self.assertEqual(
            selected.projected_binding_scopes,
            (ImportBindingScope("outer", conditional=True, deferred=True),),
        )
        self.assertIn(Definition("function", "main", "main", True, 1, 1, 1, 2), module.definitions)
        self.assertIn(
            Definition("function", "continued", "continued", True, 17, 1, 17, 19),
            module.definitions,
        )
        self.assertIn(
            Definition("function", "formfeed", "formfeed", True, 21, 1, 21, 22),
            module.definitions,
        )
        self.assertIn(SymbolUse(None, "main", 11, 7), module.calls)

    def test_top_level_async_fallback_keeps_invalid_scopes_rejected(self) -> None:
        sources = [b"def inner():\n    nonlocal missing\n"]
        if sys.version_info >= (3, 14):
            sources.append(b"class Invalid:\n    await run()\n")

        for content in sources:
            with self.subTest(content=content), self.assertRaises(PythonParseError):
                extract_structures(source_snapshot(source_file("invalid.py", content)))

    def test_extracts_import_variants_in_source_order(self) -> None:
        source = source_file(
            "imports.py",
            (
                b"import os, package.client as client\n"
                b"from .service import send as deliver, receive\n"
                b"from .. import shared\n"
                b"from plugins import *\n"
                b"def load():\n"
                b"    import local as scoped\n"
            ),
        )

        (module,) = extract_structures(source_snapshot(source))

        self.assertEqual(
            module.imports,
            (
                ImportEntry("os", None, None, 0, None, 1, 1),
                ImportEntry("package.client", None, "client", 0, None, 1, 1),
                ImportEntry("service", "send", "deliver", 1, None, 2, 1),
                ImportEntry("service", "receive", None, 1, None, 2, 1),
                ImportEntry(None, "shared", None, 2, None, 3, 1),
                ImportEntry("plugins", "*", None, 0, None, 4, 1),
                ImportEntry("local", None, "scoped", 0, "load", 6, 5),
            ),
        )

    def test_extracts_static_calls_and_load_references_without_duplicates(self) -> None:
        source = source_file(
            "calls.py",
            (
                b"def run(payload):\n"
                b"    client.send(payload)\n"
                b"    handler = client.callback\n"
                b"    (get_factory())()\n"
            ),
        )

        (module,) = extract_structures(source_snapshot(source))

        self.assertEqual(
            module.calls,
            (
                SymbolUse("run", "client.send", 2, 5),
                SymbolUse("run", "get_factory", 4, 6),
            ),
        )
        self.assertEqual(
            module.references,
            (
                SymbolUse("run", "payload", 2, 17),
                SymbolUse("run", "client.callback", 3, 15),
            ),
        )

    def test_extracts_global_and_nonlocal_declarations_by_context(self) -> None:
        source = source_file(
            "scopes.py",
            (
                b"value = 1\n"
                b"def outer():\n"
                b"    value = 2\n"
                b"    def use_nonlocal():\n"
                b"        nonlocal value\n"
                b"        return value\n"
                b"    def use_global():\n"
                b"        global value\n"
                b"        return value\n"
            ),
        )

        (module,) = extract_structures(source_snapshot(source))

        self.assertEqual(
            module.declarations,
            (
                ScopeDeclaration("nonlocal", "value", "outer.use_nonlocal", 5, 9),
                ScopeDeclaration("global", "value", "outer.use_global", 8, 9),
            ),
        )

    def test_extracts_local_store_bindings_without_inferring_values(self) -> None:
        source = source_file(
            "bindings.py",
            (
                b"def bind(items, manager, error, value):\n"
                b"    assigned = 1\n"
                b"    augmented += 1\n"
                b"    annotated: int\n"
                b"    valued: int = 2\n"
                b"    for looped in items:\n"
                b"        pass\n"
                b"    with manager() as managed:\n"
                b"        pass\n"
                b"    try:\n"
                b"        raise error\n"
                b"    except error as caught:\n"
                b"        pass\n"
                b"    match value:\n"
                b"        case {'item': captured, **rest}:\n"
                b"            pass\n"
                b"    if named := value:\n"
                b"        pass\n"
            ),
        )

        (module,) = extract_structures(source_snapshot(source))
        bindings = {
            item.name: (item.context, item.conditional, item.runtime)
            for item in module.store_bindings
        }

        self.assertEqual(
            bindings,
            {
                "annotated": ("bind", False, False),
                "assigned": ("bind", False, True),
                "augmented": ("bind", False, True),
                "caught": ("bind", True, True),
                "captured": ("bind", True, True),
                "looped": ("bind", True, True),
                "managed": ("bind", True, True),
                "named": ("bind", True, True),
                "rest": ("bind", True, True),
                "valued": ("bind", False, True),
            },
        )
        self.assertTrue(all(not item.projected_binding_scopes for item in module.store_bindings))

    def test_projects_global_and_nonlocal_store_bindings_to_their_owners(self) -> None:
        source = source_file(
            "projected_stores.py",
            (
                b"module_value = 0\n"
                b"def outer():\n"
                b"    local_value = 0\n"
                b"    def mutate():\n"
                b"        global module_value\n"
                b"        nonlocal local_value\n"
                b"        module_value = 1\n"
                b"        local_value = 2\n"
                b"    return mutate\n"
            ),
        )

        (module,) = extract_structures(source_snapshot(source))
        projected = {
            item.name: item.projected_binding_scopes
            for item in module.store_bindings
            if item.context == "outer.mutate"
        }

        self.assertEqual(
            projected,
            {
                "local_value": (ImportBindingScope("outer", conditional=True, deferred=True),),
                "module_value": (ImportBindingScope(None, conditional=True, deferred=True),),
            },
        )

    def test_projects_class_imports_to_declared_binding_scopes(self) -> None:
        source = source_file(
            "class_bindings.py",
            (
                b"class ModuleBindings:\n"
                b"    global client, service, package\n"
                b"    import package.client as client\n"
                b"    from package import service\n"
                b"    import package.client\n"
                b"    import package.local as local\n"
                b"def outer():\n"
                b"    selected = None\n"
                b"    class ClosureBindings:\n"
                b"        nonlocal selected\n"
                b"        from package import selected\n"
                b"    return ClosureBindings\n"
                b"def delayed():\n"
                b"    class ModuleBinding:\n"
                b"        global delayed_client\n"
                b"        import package.client as delayed_client\n"
                b"    return ModuleBinding\n"
                b"def function_binding():\n"
                b"    global function_client\n"
                b"    import package.client as function_client\n"
                b"def owner():\n"
                b"    owned = None\n"
                b"    def middle():\n"
                b"        class ClosureBinding:\n"
                b"            nonlocal owned\n"
                b"            import package.client as owned\n"
                b"    return middle\n"
                b"def function_owner():\n"
                b"    function_owned = None\n"
                b"    def configure():\n"
                b"        nonlocal function_owned\n"
                b"        import package.client as function_owned\n"
                b"    return configure\n"
                b"class Mismatch:\n"
                b"    global another_name\n"
                b"    import package.client as mismatch\n"
                b"def chain_owner():\n"
                b"    chained = None\n"
                b"    def middle():\n"
                b"        nonlocal chained\n"
                b"        class ClosureBinding:\n"
                b"            nonlocal chained\n"
                b"            import package.client as chained\n"
                b"    return middle\n"
                b"def late_owner():\n"
                b"    class ClosureBinding:\n"
                b"        nonlocal late\n"
                b"        import package.client as late\n"
                b"    late = None\n"
                b"    return ClosureBinding\n"
            ),
        )

        compile(source.content, source.path, "exec")
        (module,) = extract_structures(source_snapshot(source))
        imports = {item.alias or item.name or item.module: item for item in module.imports}

        for name in ("client", "service"):
            with self.subTest(name=name):
                self.assertEqual(
                    imports[name].projected_binding_scopes,
                    (ImportBindingScope(None),),
                )
        dotted = next(
            item for item in module.imports if item.module == "package.client" and not item.alias
        )
        self.assertEqual(dotted.projected_binding_scopes, (ImportBindingScope(None),))
        self.assertEqual(
            imports["selected"].projected_binding_scopes,
            (ImportBindingScope("outer"),),
        )
        self.assertEqual(
            imports["delayed_client"].projected_binding_scopes,
            (ImportBindingScope(None, conditional=True, deferred=True),),
        )
        self.assertEqual(
            imports["function_client"].projected_binding_scopes,
            (ImportBindingScope(None, conditional=True, deferred=True),),
        )
        self.assertEqual(
            imports["owned"].projected_binding_scopes,
            (ImportBindingScope("owner", conditional=True, deferred=True),),
        )
        self.assertEqual(
            imports["function_owned"].projected_binding_scopes,
            (ImportBindingScope("function_owner", conditional=True, deferred=True),),
        )
        self.assertEqual(
            imports["chained"].projected_binding_scopes,
            (ImportBindingScope("chain_owner", conditional=True, deferred=True),),
        )
        self.assertEqual(
            imports["late"].projected_binding_scopes,
            (ImportBindingScope("late_owner"),),
        )
        for name in ("local", "mismatch"):
            with self.subTest(name=name):
                self.assertEqual(imports[name].projected_binding_scopes, ())

    def test_preserves_conditions_on_nested_class_import_projections(self) -> None:
        source = source_file(
            "conditional_bindings.py",
            (
                b"if ENABLED:\n"
                b"    class ModuleBindings:\n"
                b"        global client\n"
                b"        import package.client as client\n"
                b"def outer():\n"
                b"    selected = None\n"
                b"    class Container:\n"
                b"        if ENABLED:\n"
                b"            class ClosureBindings:\n"
                b"                nonlocal selected\n"
                b"                from package import selected\n"
                b"    return Container\n"
            ),
        )

        compile(source.content, source.path, "exec")
        (module,) = extract_structures(source_snapshot(source))

        self.assertEqual(
            module.imports[0].projected_binding_scopes,
            (ImportBindingScope(None, conditional=True),),
        )
        self.assertEqual(
            module.imports[1].projected_binding_scopes,
            (ImportBindingScope("outer", conditional=True),),
        )

    def test_marks_conditional_bindings_without_leaking_into_definition_bodies(self) -> None:
        source = source_file(
            "branches.py",
            (
                b"def choose(flag):\n"
                b"    if flag:\n"
                b"        import private_api as service\n"
                b"    else:\n"
                b"        def service():\n"
                b"            import body_dependency\n"
                b"    import direct_dependency\n"
            ),
        )

        (module,) = extract_structures(source_snapshot(source))
        imports = {(item.module, item.context): item.conditional for item in module.imports}
        service = next(item for item in module.definitions if item.name == "service")

        self.assertTrue(imports[("private_api", "choose")])
        self.assertFalse(imports[("body_dependency", "choose.service")])
        self.assertFalse(imports[("direct_dependency", "choose")])
        self.assertTrue(service.conditional)

    def test_marks_lambda_and_comprehension_lookup_scopes(self) -> None:
        source = source_file(
            "synthetic.py",
            (
                b"class Worker:\n"
                b"    lambda_value = (lambda local: local())(None)\n"
                b"    values = [item() for item in items()]\n"
                b"    chained = [value for value in sources() for later in later()]\n"
            ),
        )

        (module,) = extract_structures(source_snapshot(source))
        calls = {call.target: call for call in module.calls}

        self.assertTrue(calls["local"].skip_class_scope)
        self.assertTrue(calls["local"].synthetic_local)
        self.assertFalse(calls["items"].skip_class_scope)
        self.assertFalse(calls["items"].synthetic_local)
        self.assertTrue(calls["item"].skip_class_scope)
        self.assertTrue(calls["item"].synthetic_local)
        self.assertFalse(calls["sources"].synthetic_local)
        self.assertTrue(calls["later"].skip_class_scope)
        self.assertTrue(calls["later"].synthetic_local)

    def test_attributes_definition_header_calls_to_the_enclosing_context(self) -> None:
        source = source_file(
            "definitions.py",
            (
                b"def outer():\n"
                b"    @decorate(factory())\n"
                b"    def inner(value: Value = default()) -> result_type():\n"
                b"        return body()\n"
                b"    @class_decorator(class_factory())\n"
                b"    class Child(base_factory(), metaclass=meta_factory()):\n"
                b"        class_body()\n"
                b"    async def async_inner(value=async_default()):\n"
                b"        return async_body()\n"
            ),
        )

        (module,) = extract_structures(source_snapshot(source))

        contexts = {call.target: call.context for call in module.calls}
        self.assertEqual(
            contexts,
            {
                "decorate": "outer",
                "factory": "outer",
                "default": "outer",
                "result_type": "outer",
                "body": "outer.inner",
                "class_decorator": "outer",
                "class_factory": "outer",
                "base_factory": "outer",
                "meta_factory": "outer",
                "class_body": "outer.Child",
                "async_default": "outer",
                "async_body": "outer.async_inner",
            },
        )
        self.assertEqual(len(module.calls), len(contexts))
        self.assertIn(
            SymbolUse("outer", "Value", 3, 22, lookup_limit=(3, 5)),
            module.references,
        )

    def test_omits_source_text_comments_docstrings_and_string_literals(self) -> None:
        source = source_file(
            "canaries.py",
            (
                b'"""DOCSTRING_CANARY"""\n'
                b"# COMMENT_CANARY\n"
                b'SECRET = "STRING_CANARY"\n'
                b"def run():\n"
                b'    """METHOD_DOCSTRING_CANARY"""\n'
                b'    return "RETURN_STRING_CANARY"\n'
            ),
        )

        result = extract_structures(source_snapshot(source))
        rendered = repr(result)

        self.assertEqual(
            result[0].definitions,
            (Definition("function", "run", "run", False, 4, 1, 4, 6),),
        )
        for canary in (
            "DOCSTRING_CANARY",
            "COMMENT_CANARY",
            "STRING_CANARY",
            "METHOD_DOCSTRING_CANARY",
            "RETURN_STRING_CANARY",
        ):
            with self.subTest(canary=canary):
                self.assertNotIn(canary, rendered)

    def test_reports_relative_file_and_location_without_source_line(self) -> None:
        good = source_file("a_good.py", b"VALUE = 1\n")
        invalid = source_file("package/bad.py", b"def broken(:  # ERROR_LINE_CANARY\n")

        with self.assertRaises(PythonParseError) as caught:
            extract_structures(source_snapshot(good, invalid))

        error = caught.exception
        self.assertEqual(error.path, "package/bad.py")
        self.assertEqual(error.line, 1)
        self.assertEqual(error.column, 12)
        self.assertIn("invalid syntax", error.reason)
        self.assertNotIn("ERROR_LINE_CANARY", str(error))

    def test_parses_encoding_cookie_from_memory_without_opening_files(self) -> None:
        source = source_file(
            "legacy.py",
            b'# -*- coding: latin-1 -*-\nlabel = "caf\xe9"\n',
        )

        with (
            mock.patch("builtins.open", side_effect=AssertionError("must not open source")),
            mock.patch("pathlib.Path.open", side_effect=AssertionError("must not open source")),
        ):
            result = extract_structures(source_snapshot(source))

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].path, "legacy.py")
        self.assertEqual(result[0].definitions, ())


if __name__ == "__main__":
    unittest.main()
