from __future__ import annotations

import hashlib
import json
import unittest
from dataclasses import replace

from silobrief.index import (
    IndexBuildError,
    IndexEdge,
    build_index,
    render_index_json,
    stable_node_id,
)
from silobrief.python_structure import extract_structures
from silobrief.sources import SourceFile, SourceSnapshot
from silobrief.state import DEFAULT_EXCLUDES, BoundaryData, ConfigData


def source_file(path: str, content: bytes) -> SourceFile:
    return SourceFile(
        path=path,
        content=content,
        sha256=hashlib.sha256(content).hexdigest(),
    )


def source_snapshot(*files: SourceFile) -> SourceSnapshot:
    digest = hashlib.sha256()
    for source in sorted(files, key=lambda item: item.path):
        digest.update(source.path.encode())
        digest.update(bytes.fromhex(source.sha256))
    return SourceSnapshot(files=files, warnings=(), digest=digest.hexdigest())


def config(*boundaries: BoundaryData) -> ConfigData:
    return ConfigData(
        boundaries=list(boundaries),
        default_excludes=list(DEFAULT_EXCLUDES),
        schema_version=1,
    )


class DeterministicIndexTests(unittest.TestCase):
    def test_stable_node_id_uses_path_kind_and_qualified_name(self) -> None:
        node_id = stable_node_id("package/service.py", "function", "Worker.run")

        self.assertEqual(
            node_id,
            "node-e7c8eeef16b7a03f28e3b09b380ad1bc79aea32e37840daac175804d3d8d0356",
        )
        self.assertEqual(node_id, stable_node_id("package/service.py", "function", "Worker.run"))
        self.assertNotEqual(node_id, stable_node_id("other/service.py", "function", "Worker.run"))
        self.assertNotEqual(node_id, stable_node_id("package/service.py", "class", "Worker.run"))
        self.assertNotEqual(
            node_id, stable_node_id("package/service.py", "function", "Worker.stop")
        )

    def test_builds_nodes_tokens_and_structure_edges(self) -> None:
        source = source_file(
            "package/service.py",
            (
                b'"""Service module."""\n'
                b"# Module request routing\n"
                b"import requests as http\n"
                b"def helper():\n"
                b'    """Helper docs."""\n'
                b"    # Helper comment\n"
                b"    pass\n"
                b"class Worker:\n"
                b'    """Worker docs."""\n'
                b"    # Worker coordination\n"
                b"    def execute(self):\n"
                b'        """Execute retries."""\n'
                b"        # Dispatch parcel\n"
                b"        helper()\n"
                b"        self.finish()\n"
                b"        external.call()\n"
                b"    def finish(self):\n"
                b"        pass\n"
                b'SECRET = "INDEX_STRING_CANARY"\n'
            ),
        )
        snapshot = source_snapshot(source)
        structures = extract_structures(snapshot)

        index = build_index(snapshot, structures, config())
        nodes = {node.qualified_name: node for node in index.nodes}

        self.assertEqual(
            set(nodes), {"package.service", "helper", "Worker", "Worker.execute", "Worker.finish"}
        )
        execute = nodes["Worker.execute"]
        self.assertEqual(execute.tokens.path, ("package", "service"))
        self.assertEqual(execute.tokens.symbol, ("execute", "worker"))
        self.assertEqual(execute.tokens.imports, ("http", "requests"))
        self.assertEqual(execute.tokens.comments, ("dispatch", "parcel"))
        self.assertEqual(execute.tokens.docstrings, ("execute", "retries"))

        module = nodes["package.service"]
        worker = nodes["Worker"]
        helper = nodes["helper"]
        finish = nodes["Worker.finish"]
        self.assertEqual(module.tokens.comments, ("module", "request", "routing"))
        self.assertEqual(module.tokens.docstrings, ("module", "service"))
        self.assertEqual(worker.tokens.comments, ("coordination", "worker"))
        self.assertEqual(worker.tokens.docstrings, ("docs", "worker"))
        self.assertEqual(helper.tokens.comments, ("comment", "helper"))
        self.assertEqual(helper.tokens.docstrings, ("docs", "helper"))
        self.assertEqual(finish.tokens.comments, ())
        self.assertEqual(finish.tokens.docstrings, ())
        self.assertEqual(
            set(index.edges),
            {
                IndexEdge(module.id, "contains", "helper", helper.id),
                IndexEdge(module.id, "contains", "Worker", worker.id),
                IndexEdge(worker.id, "contains", "Worker.execute", execute.id),
                IndexEdge(worker.id, "contains", "Worker.finish", finish.id),
                IndexEdge(module.id, "import", "requests", None),
                IndexEdge(execute.id, "call", "helper", helper.id),
                IndexEdge(execute.id, "call", "self.finish", finish.id),
                IndexEdge(execute.id, "call", "external.call", None),
            },
        )

    def test_module_text_tokens_are_not_copied_to_definition_nodes(self) -> None:
        source = source_file(
            "module.py",
            (
                b'"""Unique module documentation."""\n'
                b"# Unique module comment\n"
                b"def first():\n"
                b"    pass\n"
                b"def second():\n"
                b"    pass\n"
            ),
        )
        snapshot = source_snapshot(source)

        index = build_index(snapshot, extract_structures(snapshot), config())
        nodes = {node.qualified_name: node for node in index.nodes}

        self.assertIn("documentation", nodes["module"].tokens.docstrings)
        self.assertIn("comment", nodes["module"].tokens.comments)
        for name in ("first", "second"):
            with self.subTest(name=name):
                self.assertNotIn("documentation", nodes[name].tokens.docstrings)
                self.assertNotIn("comment", nodes[name].tokens.comments)

    def test_resolves_absolute_imports_and_calls_across_src_layout_modules(self) -> None:
        caller = source_file(
            "src/pkg/a.py",
            b"from pkg.b import helper\n\ndef run():\n    return helper()\n",
        )
        dependency = source_file("src/pkg/b.py", b"def helper():\n    return 42\n")
        snapshot = source_snapshot(caller, dependency)

        index = build_index(snapshot, extract_structures(snapshot), config())
        nodes = {(node.path, node.kind, node.qualified_name): node for node in index.nodes}
        caller_module = nodes[("src/pkg/a.py", "module", "pkg.a")]
        dependency_function = nodes[("src/pkg/b.py", "function", "helper")]
        run = nodes[("src/pkg/a.py", "function", "run")]

        self.assertIn(
            IndexEdge(caller_module.id, "import", "pkg.b.helper", dependency_function.id),
            index.edges,
        )
        self.assertIn(
            IndexEdge(run.id, "call", "helper", dependency_function.id),
            index.edges,
        )

    def test_resolves_relative_and_aliased_import_calls(self) -> None:
        caller = source_file(
            "src/pkg/feature.py",
            (
                b"from .b import helper as local_helper\n"
                b"import pkg.b as module_alias\n"
                b"import pkg.b\n\n"
                b"def run():\n"
                b"    local_helper()\n"
                b"    module_alias.helper()\n"
                b"    pkg.b.helper()\n"
            ),
        )
        dependency = source_file("src/pkg/b.py", b"def helper():\n    return 42\n")
        snapshot = source_snapshot(caller, dependency)

        index = build_index(snapshot, extract_structures(snapshot), config())
        nodes = {(node.path, node.kind, node.qualified_name): node for node in index.nodes}
        caller_module = nodes[("src/pkg/feature.py", "module", "pkg.feature")]
        dependency_module = nodes[("src/pkg/b.py", "module", "pkg.b")]
        dependency_function = nodes[("src/pkg/b.py", "function", "helper")]
        run = nodes[("src/pkg/feature.py", "function", "run")]

        self.assertIn(
            IndexEdge(caller_module.id, "import", "pkg.b.helper", dependency_function.id),
            index.edges,
        )
        self.assertIn(
            IndexEdge(caller_module.id, "import", "pkg.b", dependency_module.id),
            index.edges,
        )
        self.assertIn(
            IndexEdge(run.id, "call", "local_helper", dependency_function.id),
            index.edges,
        )
        self.assertIn(
            IndexEdge(run.id, "call", "module_alias.helper", dependency_function.id),
            index.edges,
        )
        self.assertIn(
            IndexEdge(run.id, "call", "pkg.b.helper", dependency_function.id),
            index.edges,
        )

    def test_resolves_definitions_in_python_lexical_scopes(self) -> None:
        source = source_file(
            "scope_demo.py",
            (
                b"def helper():\n"
                b"    return 'global'\n"
                b"def outer():\n"
                b"    def helper():\n"
                b"        return 'local'\n"
                b"    return helper()\n"
                b"class Worker:\n"
                b"    def helper(self):\n"
                b"        return 'method'\n"
                b"    def run(self):\n"
                b"        helper()\n"
                b"        def inner():\n"
                b"            return self.helper()\n"
                b"        return inner()\n"
                b"    @classmethod\n"
                b"    def create(cls):\n"
                b"        return cls.helper()\n"
            ),
        )
        snapshot = source_snapshot(source)

        index = build_index(snapshot, extract_structures(snapshot), config())
        nodes = {node.qualified_name: node for node in index.nodes}

        self.assertIn(
            IndexEdge(
                nodes["outer"].id,
                "call",
                "helper",
                nodes["outer.helper"].id,
            ),
            index.edges,
        )
        self.assertIn(
            IndexEdge(
                nodes["Worker.run"].id,
                "call",
                "helper",
                nodes["helper"].id,
            ),
            index.edges,
        )
        self.assertIn(
            IndexEdge(
                nodes["Worker.run"].id,
                "call",
                "inner",
                nodes["Worker.run.inner"].id,
            ),
            index.edges,
        )
        self.assertIn(
            IndexEdge(
                nodes["Worker.run.inner"].id,
                "call",
                "self.helper",
                nodes["Worker.helper"].id,
            ),
            index.edges,
        )
        self.assertIn(
            IndexEdge(
                nodes["Worker.create"].id,
                "call",
                "cls.helper",
                nodes["Worker.helper"].id,
            ),
            index.edges,
        )

    def test_resolves_imports_in_python_lexical_scopes(self) -> None:
        caller = source_file(
            "caller.py",
            (
                b"from pkg import global_target as alias\n"
                b"def outer():\n"
                b"    from pkg import local_target as alias\n"
                b"    def inner():\n"
                b"        return alias()\n"
                b"    class NestedWorker:\n"
                b"        from pkg import class_target as alias\n"
                b"        def run(self):\n"
                b"            return alias()\n"
                b"    return inner()\n"
                b"class Worker:\n"
                b"    from pkg import class_target as alias\n"
                b"    value = alias()\n"
                b"    def run(self):\n"
                b"        return alias()\n"
            ),
        )
        dependency = source_file(
            "pkg.py",
            (
                b"def global_target():\n"
                b"    return 'global'\n"
                b"def local_target():\n"
                b"    return 'local'\n"
                b"def class_target():\n"
                b"    return 'class'\n"
            ),
        )
        snapshot = source_snapshot(caller, dependency)

        index = build_index(snapshot, extract_structures(snapshot), config())
        nodes = {(node.path, node.qualified_name): node for node in index.nodes}

        self.assertIn(
            IndexEdge(
                nodes[("caller.py", "outer.inner")].id,
                "call",
                "alias",
                nodes[("pkg.py", "local_target")].id,
            ),
            index.edges,
        )
        self.assertIn(
            IndexEdge(
                nodes[("caller.py", "Worker")].id,
                "call",
                "alias",
                nodes[("pkg.py", "class_target")].id,
            ),
            index.edges,
        )
        self.assertIn(
            IndexEdge(
                nodes[("caller.py", "Worker.run")].id,
                "call",
                "alias",
                nodes[("pkg.py", "global_target")].id,
            ),
            index.edges,
        )
        self.assertIn(
            IndexEdge(
                nodes[("caller.py", "outer.NestedWorker.run")].id,
                "call",
                "alias",
                nodes[("pkg.py", "local_target")].id,
            ),
            index.edges,
        )

    def test_local_import_takes_priority_over_outer_definition(self) -> None:
        caller = source_file(
            "caller.py",
            (
                b"def helper():\n"
                b"    return 'global'\n"
                b"def outer():\n"
                b"    from pkg import helper\n"
                b"    return helper()\n"
            ),
        )
        dependency = source_file("pkg.py", b"def helper():\n    return 'imported'\n")
        snapshot = source_snapshot(caller, dependency)

        index = build_index(snapshot, extract_structures(snapshot), config())
        nodes = {(node.path, node.qualified_name): node for node in index.nodes}

        self.assertIn(
            IndexEdge(
                nodes[("caller.py", "outer")].id,
                "call",
                "helper",
                nodes[("pkg.py", "helper")].id,
            ),
            index.edges,
        )

    def test_uses_the_latest_definition_or_import_in_the_same_scope(self) -> None:
        caller = source_file(
            "caller.py",
            (
                b"def imported_last():\n"
                b"    def helper():\n"
                b"        return 'local'\n"
                b"    from pkg import helper\n"
                b"    callback = helper\n"
                b"    return helper()\n"
                b"def defined_last():\n"
                b"    from pkg import helper\n"
                b"    def helper():\n"
                b"        return 'local'\n"
                b"    callback = helper\n"
                b"    return helper()\n"
            ),
        )
        dependency = source_file("pkg.py", b"def helper():\n    return 'imported'\n")
        snapshot = source_snapshot(caller, dependency)

        index = build_index(snapshot, extract_structures(snapshot), config())
        nodes = {(node.path, node.qualified_name): node for node in index.nodes}
        imported = nodes[("pkg.py", "helper")]
        local = nodes[("caller.py", "defined_last.helper")]

        for kind in ("call", "reference"):
            with self.subTest(scope="imported_last", kind=kind):
                self.assertIn(
                    IndexEdge(
                        nodes[("caller.py", "imported_last")].id,
                        kind,
                        "helper",
                        imported.id,
                    ),
                    index.edges,
                )
            with self.subTest(scope="defined_last", kind=kind):
                self.assertIn(
                    IndexEdge(
                        nodes[("caller.py", "defined_last")].id,
                        kind,
                        "helper",
                        local.id,
                    ),
                    index.edges,
                )

    def test_calls_follow_repeated_import_rebindings(self) -> None:
        caller = source_file(
            "caller.py",
            (
                b"def choose():\n"
                b"    from first import target as selected\n"
                b"    selected()\n"
                b"    from second import target as selected\n"
                b"    selected()\n"
            ),
        )
        first = source_file("first.py", b"def target():\n    return 1\n")
        second = source_file("second.py", b"def target():\n    return 2\n")
        snapshot = source_snapshot(caller, first, second)

        index = build_index(snapshot, extract_structures(snapshot), config())
        nodes = {(node.path, node.qualified_name): node for node in index.nodes}
        choose = nodes[("caller.py", "choose")]

        self.assertIn(
            IndexEdge(choose.id, "call", "selected", nodes[("first.py", "target")].id),
            index.edges,
        )
        self.assertIn(
            IndexEdge(choose.id, "call", "selected", nodes[("second.py", "target")].id),
            index.edges,
        )

    def test_nested_uses_take_the_latest_binding_before_their_definition(self) -> None:
        caller = source_file(
            "caller.py",
            (
                b"from first import target as module_selected\n"
                b"from second import target as module_selected\n"
                b"def module_user():\n"
                b"    return module_selected()\n"
                b"def outer():\n"
                b"    from first import target as local_selected\n"
                b"    from second import target as local_selected\n"
                b"    def inner():\n"
                b"        return local_selected()\n"
                b"    return inner\n"
            ),
        )
        first = source_file("first.py", b"def target():\n    return 1\n")
        second = source_file("second.py", b"def target():\n    return 2\n")
        snapshot = source_snapshot(caller, first, second)

        index = build_index(snapshot, extract_structures(snapshot), config())
        nodes = {(node.path, node.qualified_name): node for node in index.nodes}
        second_target = nodes[("second.py", "target")]

        for qualified_name, target in (
            ("module_user", "module_selected"),
            ("outer.inner", "local_selected"),
        ):
            with self.subTest(qualified_name=qualified_name):
                self.assertIn(
                    IndexEdge(
                        nodes[("caller.py", qualified_name)].id,
                        "call",
                        target,
                        second_target.id,
                    ),
                    index.edges,
                )

    def test_function_bodies_resolve_module_bindings_defined_later(self) -> None:
        caller = source_file(
            "caller.py",
            (
                b"def run():\n"
                b"    Later()\n"
                b"    return selected()\n"
                b"class Later:\n"
                b"    pass\n"
                b"from dependency import target as selected\n"
            ),
        )
        dependency = source_file("dependency.py", b"def target():\n    return 1\n")
        snapshot = source_snapshot(caller, dependency)

        index = build_index(snapshot, extract_structures(snapshot), config())
        nodes = {(node.path, node.qualified_name): node for node in index.nodes}
        run = nodes[("caller.py", "run")]

        self.assertIn(
            IndexEdge(run.id, "call", "Later", nodes[("caller.py", "Later")].id), index.edges
        )
        self.assertIn(
            IndexEdge(run.id, "call", "selected", nodes[("dependency.py", "target")].id),
            index.edges,
        )

    def test_declarations_are_scoped_to_each_duplicate_definition_body(self) -> None:
        caller = source_file(
            "caller.py",
            (
                b"from module_api import target as selected\n"
                b"def outer():\n"
                b"    from local_api import target as selected\n"
                b"    def duplicate():\n"
                b"        global selected\n"
                b"        return selected()\n"
                b"    def duplicate():\n"
                b"        return selected()\n"
                b"    return duplicate()\n"
            ),
        )
        module_api = source_file("module_api.py", b"def target():\n    return 1\n")
        local_api = source_file("local_api.py", b"def target():\n    return 2\n")
        snapshot = source_snapshot(caller, module_api, local_api)

        index = build_index(snapshot, extract_structures(snapshot), config())
        nodes = {(node.path, node.qualified_name): node for node in index.nodes}
        duplicate = nodes[("caller.py", "outer.duplicate")]

        self.assertIn(
            IndexEdge(duplicate.id, "call", "selected", nodes[("module_api.py", "target")].id),
            index.edges,
        )
        self.assertIn(
            IndexEdge(duplicate.id, "call", "selected", nodes[("local_api.py", "target")].id),
            index.edges,
        )

    def test_class_only_import_is_not_visible_to_a_method(self) -> None:
        caller = source_file(
            "caller.py",
            (
                b"class Worker:\n"
                b"    from pkg import helper as alias\n"
                b"    def run(self):\n"
                b"        return alias()\n"
            ),
        )
        dependency = source_file("pkg.py", b"def helper():\n    return 1\n")
        snapshot = source_snapshot(caller, dependency)

        index = build_index(snapshot, extract_structures(snapshot), config())
        nodes = {(node.path, node.qualified_name): node for node in index.nodes}
        call = next(
            edge
            for edge in index.edges
            if edge.source_id == nodes[("caller.py", "Worker.run")].id and edge.kind == "call"
        )

        self.assertEqual(call.target, "alias")
        self.assertIsNone(call.target_id)

    def test_dotted_import_binds_the_top_level_package_name(self) -> None:
        caller = source_file(
            "caller.py",
            (
                b"def pkg():\n"
                b"    return 'function'\n"
                b"def run():\n"
                b"    import pkg.sub\n"
                b"    return pkg\n"
            ),
        )
        package = source_file("pkg/__init__.py", b"VALUE = 1\n")
        dependency = source_file("pkg/sub.py", b"VALUE = 2\n")
        snapshot = source_snapshot(caller, package, dependency)

        index = build_index(snapshot, extract_structures(snapshot), config())
        nodes = {(node.path, node.qualified_name): node for node in index.nodes}

        self.assertIn(
            IndexEdge(
                nodes[("caller.py", "run")].id,
                "reference",
                "pkg",
                nodes[("pkg/__init__.py", "pkg")].id,
            ),
            index.edges,
        )

    def test_declaration_scope_imports_override_existing_outer_bindings(self) -> None:
        caller = source_file(
            "caller.py",
            (
                b"from first import target as selected\n"
                b"def use_global():\n"
                b"    global selected\n"
                b"    from second import target as selected\n"
                b"    return selected()\n"
                b"def outer():\n"
                b"    from first import target as selected\n"
                b"    def use_nonlocal():\n"
                b"        nonlocal selected\n"
                b"        from second import target as selected\n"
                b"        return selected()\n"
                b"    return use_nonlocal()\n"
            ),
        )
        first = source_file("first.py", b"def target():\n    return 1\n")
        second = source_file("second.py", b"def target():\n    return 2\n")
        snapshot = source_snapshot(caller, first, second)

        index = build_index(snapshot, extract_structures(snapshot), config())
        nodes = {(node.path, node.qualified_name): node for node in index.nodes}
        second_target = nodes[("second.py", "target")]

        for qualified_name in ("use_global", "outer.use_nonlocal"):
            with self.subTest(qualified_name=qualified_name):
                self.assertIn(
                    IndexEdge(
                        nodes[("caller.py", qualified_name)].id,
                        "call",
                        "selected",
                        second_target.id,
                    ),
                    index.edges,
                )

    def test_class_declaration_imports_update_their_actual_outer_scopes(self) -> None:
        caller = source_file(
            "caller.py",
            (
                b"from first import target as module_selected\n"
                b"class ModuleWriter:\n"
                b"    global module_selected\n"
                b"    from second import target as module_selected\n"
                b"    def use_module(self):\n"
                b"        return module_selected()\n"
                b"def after_module_class():\n"
                b"    return module_selected()\n"
                b"def outer():\n"
                b"    from first import target as closure_selected\n"
                b"    class ClosureWriter:\n"
                b"        nonlocal closure_selected\n"
                b"        from second import target as closure_selected\n"
                b"        def use_closure(self):\n"
                b"            return closure_selected()\n"
                b"    def after_closure_class():\n"
                b"        return closure_selected()\n"
                b"    return ClosureWriter, after_closure_class\n"
            ),
        )
        first = source_file("first.py", b"def target():\n    return 1\n")
        second = source_file("second.py", b"def target():\n    return 2\n")
        snapshot = source_snapshot(caller, first, second)

        index = build_index(snapshot, extract_structures(snapshot), config())
        nodes = {(node.path, node.qualified_name): node for node in index.nodes}
        second_target = nodes[("second.py", "target")]

        for qualified_name, target in (
            ("ModuleWriter.use_module", "module_selected"),
            ("after_module_class", "module_selected"),
            ("outer.ClosureWriter.use_closure", "closure_selected"),
            ("outer.after_closure_class", "closure_selected"),
        ):
            with self.subTest(qualified_name=qualified_name):
                self.assertIn(
                    IndexEdge(
                        nodes[("caller.py", qualified_name)].id,
                        "call",
                        target,
                        second_target.id,
                    ),
                    index.edges,
                )

    def test_redefinition_uses_the_latest_definition_node_kind(self) -> None:
        source = source_file(
            "caller.py",
            (
                b"def Target():\n"
                b"    return 'function'\n"
                b"class Target:\n"
                b"    def helper(self):\n"
                b"        return 'method'\n"
                b"    def run(self):\n"
                b"        helper()\n"
                b"        return self.helper()\n"
                b"Target()\n"
            ),
        )
        snapshot = source_snapshot(source)

        index = build_index(snapshot, extract_structures(snapshot), config())
        nodes = {(node.kind, node.qualified_name): node for node in index.nodes}

        self.assertIn(
            IndexEdge(
                nodes[("module", "caller")].id,
                "call",
                "Target",
                nodes[("class", "Target")].id,
            ),
            index.edges,
        )
        self.assertIn(
            IndexEdge(
                nodes[("function", "Target.run")].id,
                "call",
                "self.helper",
                nodes[("function", "Target.helper")].id,
            ),
            index.edges,
        )
        self.assertIn(
            IndexEdge(nodes[("function", "Target.run")].id, "call", "helper", None),
            index.edges,
        )
        self.assertNotIn(
            IndexEdge(
                nodes[("function", "Target.run")].id,
                "call",
                "helper",
                nodes[("function", "Target.helper")].id,
            ),
            index.edges,
        )

    def test_function_redefinition_keeps_its_nested_function_scope(self) -> None:
        source = source_file(
            "caller.py",
            (
                b"class Target:\n"
                b"    pass\n"
                b"def Target():\n"
                b"    def helper():\n"
                b"        return 'nested'\n"
                b"    def run():\n"
                b"        return helper()\n"
                b"    return run()\n"
            ),
        )
        snapshot = source_snapshot(source)

        index = build_index(snapshot, extract_structures(snapshot), config())
        nodes = {(node.kind, node.qualified_name): node for node in index.nodes}

        self.assertIn(
            IndexEdge(
                nodes[("function", "Target.run")].id,
                "call",
                "helper",
                nodes[("function", "Target.helper")].id,
            ),
            index.edges,
        )

    def test_synthetic_scopes_skip_class_bindings_and_keep_local_names_unresolved(self) -> None:
        source = source_file(
            "caller.py",
            (
                b"def helper():\n"
                b"    return 'module'\n"
                b"def lambda_local():\n"
                b"    return 'module'\n"
                b"def comprehension_local():\n"
                b"    return 'module'\n"
                b"class Worker:\n"
                b"    def helper():\n"
                b"        return 'class'\n"
                b"    lambda_value = (lambda: helper())()\n"
                b"    comprehension_value = [helper() for _ in ()]\n"
                b"    lambda_shadow = (lambda lambda_local: lambda_local())(None)\n"
                b"    comprehension_shadow = "
                b"[comprehension_local() for comprehension_local in ()]\n"
            ),
        )
        snapshot = source_snapshot(source)

        index = build_index(snapshot, extract_structures(snapshot), config())
        nodes = {node.qualified_name: node for node in index.nodes}
        worker = nodes["Worker"]

        self.assertIn(
            IndexEdge(worker.id, "call", "helper", nodes["helper"].id),
            index.edges,
        )
        self.assertNotIn(
            IndexEdge(worker.id, "call", "helper", nodes["Worker.helper"].id),
            index.edges,
        )
        for name in ("lambda_local", "comprehension_local"):
            with self.subTest(name=name):
                self.assertIn(IndexEdge(worker.id, "call", name, None), index.edges)
                self.assertNotIn(
                    IndexEdge(worker.id, "call", name, nodes[name].id),
                    index.edges,
                )

    def test_definition_header_resolves_the_previous_import_binding(self) -> None:
        caller = source_file(
            "caller.py",
            b"from pkg import Base\nclass Base(Base):\n    pass\n",
        )
        dependency = source_file("pkg.py", b"class Base:\n    pass\n")
        snapshot = source_snapshot(caller, dependency)

        index = build_index(snapshot, extract_structures(snapshot), config())
        nodes = {(node.path, node.kind, node.qualified_name): node for node in index.nodes}
        caller_module = nodes[("caller.py", "module", "caller")]

        self.assertIn(
            IndexEdge(
                caller_module.id,
                "reference",
                "Base",
                nodes[("pkg.py", "class", "Base")].id,
            ),
            index.edges,
        )

    def test_json_is_identical_for_equivalent_input_order(self) -> None:
        first_source = source_file(
            "a.py",
            b'"""Alpha docs."""\n# Useful comment\nVALUE = "STRING_LITERAL_CANARY"\n',
        )
        second_source = source_file("package/b.py", b"def BetaValue():\n    pass\n")
        first_snapshot = source_snapshot(first_source, second_source)
        second_snapshot = source_snapshot(second_source, first_source)
        first_structures = extract_structures(first_snapshot)
        second_structures = tuple(reversed(extract_structures(second_snapshot)))
        private = BoundaryData(alias="private", description="Private code", path="private")
        generated = BoundaryData(alias="generated", description="Generated code", path="gen")

        first = build_index(first_snapshot, first_structures, config(private, generated))
        second = build_index(second_snapshot, second_structures, config(generated, private))
        first_json = render_index_json(first)
        second_json = render_index_json(second)

        self.assertEqual(first, second)
        self.assertEqual(first_json, second_json)
        self.assertTrue(first_json.endswith(b"\n"))
        self.assertFalse(first_json.endswith(b"\n\n"))
        self.assertNotIn(b"\r\n", first_json)
        self.assertNotIn(b"STRING_LITERAL_CANARY", first_json)
        parsed = json.loads(first_json)
        self.assertEqual(
            set(parsed),
            {"config_digest", "edges", "index_version", "nodes", "source_digest", "stale"},
        )
        self.assertEqual(parsed["index_version"], 1)
        self.assertIs(parsed["stale"], False)

    def test_config_and_source_digest_changes_are_visible(self) -> None:
        source = source_file("module.py", b"VALUE = 1\n")
        snapshot = source_snapshot(source)
        structures = extract_structures(snapshot)
        original = build_index(
            snapshot,
            structures,
            config(BoundaryData(alias="private", description="Private code", path="private")),
        )
        changed_config = build_index(
            snapshot,
            structures,
            config(BoundaryData(alias="private", description="Internal code", path="private")),
        )
        changed_source = build_index(
            replace(snapshot, digest="f" * 64),
            structures,
            config(BoundaryData(alias="private", description="Private code", path="private")),
        )

        self.assertNotEqual(original.config_digest, changed_config.config_digest)
        self.assertEqual(original.source_digest, changed_config.source_digest)
        self.assertEqual(original.config_digest, changed_source.config_digest)
        self.assertNotEqual(original.source_digest, changed_source.source_digest)

    def test_rejects_mismatched_source_and_structure_paths(self) -> None:
        snapshot = source_snapshot(source_file("module.py", b"VALUE = 1\n"))

        with self.assertRaisesRegex(IndexBuildError, "paths do not match"):
            build_index(snapshot, (), config())


if __name__ == "__main__":
    unittest.main()
