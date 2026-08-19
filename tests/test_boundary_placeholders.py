from __future__ import annotations

import hashlib
import unittest

from silobrief.boundary_placeholders import BoundaryPlaceholder
from silobrief.index import build_index, render_index_json
from silobrief.python_structure import extract_structures
from silobrief.sources import SourceFile, SourceSnapshot
from silobrief.state import DEFAULT_EXCLUDES, BoundaryData, ConfigData


def source_snapshot(path: str, content: bytes) -> SourceSnapshot:
    source = SourceFile(
        path=path,
        content=content,
        sha256=hashlib.sha256(content).hexdigest(),
    )
    return SourceSnapshot(files=(source,), warnings=(), digest="a" * 64)


def config(*boundaries: BoundaryData) -> ConfigData:
    return ConfigData(
        boundaries=list(boundaries),
        default_excludes=list(DEFAULT_EXCLUDES),
        schema_version=1,
    )


class BoundaryPlaceholderTests(unittest.TestCase):
    def test_replaces_absolute_import_for_src_layout_boundary(self) -> None:
        snapshot = source_snapshot(
            "src/pkg/app.py",
            (
                b"from pkg.secretmod import hidden_internal_name\n"
                b"def run():\n"
                b"    return hidden_internal_name()\n"
            ),
        )
        boundary = BoundaryData(
            alias="secret-boundary",
            description="Approved internal module",
            path="src/pkg/secretmod.py",
        )

        rendered = render_index_json(
            build_index(snapshot, extract_structures(snapshot), config(boundary))
        )

        self.assertIn(b'"alias": "secret-boundary"', rendered)
        self.assertIn(b'"description": "Approved internal module"', rendered)
        for forbidden in (b"pkg.secretmod", b"secretmod", b"hidden_internal_name"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, rendered)

    def test_replaces_directory_boundary_imports_calls_and_references(self) -> None:
        snapshot = source_snapshot(
            "app.py",
            (
                b"from vault_private.gateway import SecretClient as hidden_client\n"
                b"import vault_private.worker as hidden_worker\n"
                b"import requests as http\n"
                b"def run():\n"
                b"    client = hidden_client\n"
                b"    hidden_client()\n"
                b"    hidden_worker.execute()\n"
                b"    vault_private.worker.status\n"
                b"    http.get()\n"
            ),
        )
        boundary = BoundaryData(
            alias="internal-service",
            description="Approved internal service",
            path="vault_private",
        )

        rendered = render_index_json(
            build_index(snapshot, extract_structures(snapshot), config(boundary))
        )

        placeholder = (
            b'{\n        "alias": "internal-service",\n'
            b'        "description": "Approved internal service",\n'
            b'        "kind": "boundary-placeholder"\n      }'
        )
        self.assertIn(placeholder, rendered)
        self.assertIn(b'"target": "requests"', rendered)
        self.assertIn(b'"target": "requests.get"', rendered)
        self.assertIn(
            b'"imports": [\n          "approved",\n          "http",\n'
            b'          "internal",\n          "requests",\n          "service"\n        ]',
            rendered,
        )
        for forbidden in (
            b"vault_private",
            b"gateway",
            b"SecretClient",
            b"secret",
            b"client",
            b"hidden_client",
            b"hidden_worker",
            b"worker",
            b"status",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, rendered)

    def test_resolves_relative_file_boundary_deterministically(self) -> None:
        snapshot = source_snapshot(
            "package/public.py",
            (
                b"from .private_zone import HiddenThing as local_hidden\n"
                b"def build():\n"
                b"    return local_hidden\n"
            ),
        )
        private = BoundaryData(
            alias="internal-module",
            description="Approved module",
            path="package/private_zone.py",
        )
        unused = BoundaryData(
            alias="unused-boundary",
            description="Unused boundary",
            path="unused",
        )
        structures = extract_structures(snapshot)

        first = render_index_json(build_index(snapshot, structures, config(private, unused)))
        second = render_index_json(build_index(snapshot, structures, config(unused, private)))

        self.assertEqual(first, second)
        self.assertIn(b'"alias": "internal-module"', first)
        self.assertIn(b'"description": "Approved module"', first)
        for forbidden in (b"private_zone", b"HiddenThing", b"local_hidden"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, first)

    def test_method_boundary_lookup_skips_the_class_namespace(self) -> None:
        source = source_snapshot(
            "service.py",
            (
                b"from private_zone import send\n"
                b"class Service:\n"
                b"    from public_api import send\n"
                b"    def run(self):\n"
                b"        return send()\n"
            ),
        )
        boundary = BoundaryData(
            alias="private-service",
            description="Approved private service",
            path="private_zone.py",
        )

        index = build_index(source, extract_structures(source), config(boundary))
        run = next(node for node in index.nodes if node.qualified_name == "Service.run")
        call = next(
            edge for edge in index.edges if edge.source_id == run.id and edge.kind == "call"
        )

        self.assertEqual(
            call.target,
            BoundaryPlaceholder("private-service", "Approved private service"),
        )
        self.assertIsNone(call.target_id)

    def test_class_global_does_not_hide_an_enclosing_function_boundary(self) -> None:
        source = source_snapshot(
            "service.py",
            (
                b"def outer():\n"
                b"    import private_zone as selected\n"
                b"    class Service:\n"
                b"        global selected\n"
                b"        import public_zone as selected\n"
                b"        def run(self):\n"
                b"            return selected.HiddenClient()\n"
                b"    return Service\n"
            ),
        )
        boundary = BoundaryData(
            alias="private-service",
            description="Approved private service",
            path="private_zone.py",
        )

        index = build_index(source, extract_structures(source), config(boundary))
        run = next(node for node in index.nodes if node.qualified_name == "outer.Service.run")
        call = next(
            edge for edge in index.edges if edge.source_id == run.id and edge.kind == "call"
        )

        self.assertEqual(
            call.target,
            BoundaryPlaceholder("private-service", "Approved private service"),
        )
        self.assertIsNone(call.target_id)
        rendered = render_index_json(index)
        for forbidden in (b"private_zone", b"HiddenClient"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, rendered)

    def test_parameter_shadows_a_module_boundary_import(self) -> None:
        source = source_snapshot(
            "service.py",
            b"from private_zone import send\ndef run(send):\n    return send()\n",
        )
        boundary = BoundaryData(
            alias="private-service",
            description="Approved private service",
            path="private_zone.py",
        )

        index = build_index(source, extract_structures(source), config(boundary))
        run = next(node for node in index.nodes if node.qualified_name == "run")
        call = next(
            edge for edge in index.edges if edge.source_id == run.id and edge.kind == "call"
        )

        self.assertEqual(call.target, "send")
        self.assertIsNone(call.target_id)

    def test_receiver_import_shadows_the_enclosing_method_parameter(self) -> None:
        source = source_snapshot(
            "service.py",
            (
                b"class Service:\n"
                b"    def helper(self):\n"
                b"        return 'public'\n"
                b"    def run(self):\n"
                b"        from private_zone import client as self\n"
                b"        def inner():\n"
                b"            return self.helper()\n"
                b"        return inner\n"
            ),
        )
        boundary = BoundaryData(
            alias="private-service",
            description="Approved private service",
            path="private_zone.py",
        )

        index = build_index(source, extract_structures(source), config(boundary))
        inner = next(node for node in index.nodes if node.qualified_name == "Service.run.inner")
        call = next(
            edge for edge in index.edges if edge.source_id == inner.id and edge.kind == "call"
        )

        self.assertEqual(
            call.target,
            BoundaryPlaceholder("private-service", "Approved private service"),
        )
        self.assertIsNone(call.target_id)

    def test_global_declaration_skips_an_enclosing_function_import(self) -> None:
        source = source_snapshot(
            "service.py",
            (
                b"import private_zone as service\n"
                b"def outer():\n"
                b"    import public_api as service\n"
                b"    def inner():\n"
                b"        global service\n"
                b"        return service.send()\n"
                b"    return inner\n"
            ),
        )
        boundary = BoundaryData(
            alias="private-service",
            description="Approved private service",
            path="private_zone.py",
        )

        index = build_index(source, extract_structures(source), config(boundary))
        inner = next(node for node in index.nodes if node.qualified_name == "outer.inner")
        call = next(
            edge for edge in index.edges if edge.source_id == inner.id and edge.kind == "call"
        )

        self.assertEqual(
            call.target,
            BoundaryPlaceholder("private-service", "Approved private service"),
        )
        self.assertIsNone(call.target_id)

    def test_source_order_resolves_boundary_import_and_local_definition(self) -> None:
        source = source_snapshot(
            "service.py",
            (
                b"def imported_last():\n"
                b"    def service():\n"
                b"        return 'public'\n"
                b"    from private_zone import client as service\n"
                b"    return service()\n"
                b"def defined_last():\n"
                b"    from private_zone import client as service\n"
                b"    def service():\n"
                b"        return 'public'\n"
                b"    return service()\n"
            ),
        )
        boundary = BoundaryData(
            alias="private-service",
            description="Approved private service",
            path="private_zone.py",
        )

        index = build_index(source, extract_structures(source), config(boundary))
        nodes = {node.qualified_name: node for node in index.nodes}
        imported_call = next(
            edge
            for edge in index.edges
            if edge.source_id == nodes["imported_last"].id and edge.kind == "call"
        )
        defined_call = next(
            edge
            for edge in index.edges
            if edge.source_id == nodes["defined_last"].id and edge.kind == "call"
        )

        self.assertEqual(
            imported_call.target,
            BoundaryPlaceholder("private-service", "Approved private service"),
        )
        self.assertIsNone(imported_call.target_id)
        self.assertEqual(defined_call.target, "service")
        self.assertEqual(defined_call.target_id, nodes["defined_last.service"].id)
        self.assertNotIn(b"private_zone", render_index_json(index))

    def test_lexical_bindings_shadow_a_raw_boundary_name(self) -> None:
        source = source_snapshot(
            "service.py",
            (
                b"def use_local():\n"
                b"    def private():\n"
                b"        return 'local'\n"
                b"    return private()\n"
                b"def use_parameter(private):\n"
                b"    return private()\n"
                b"def use_public_import():\n"
                b"    from public_api import helper as private\n"
                b"    return private()\n"
            ),
        )
        boundary = BoundaryData(
            alias="private-code",
            description="Approved private code",
            path="private.py",
        )

        index = build_index(source, extract_structures(source), config(boundary))
        nodes = {node.qualified_name: node for node in index.nodes}
        calls = {
            node_name: next(
                edge
                for edge in index.edges
                if edge.source_id == nodes[node_name].id and edge.kind == "call"
            )
            for node_name in ("use_local", "use_parameter", "use_public_import")
        }

        self.assertEqual(calls["use_local"].target, "private")
        self.assertEqual(
            calls["use_local"].target_id,
            nodes["use_local.private"].id,
        )
        self.assertEqual(calls["use_parameter"].target, "private")
        self.assertIsNone(calls["use_parameter"].target_id)
        self.assertEqual(calls["use_public_import"].target, "public_api.helper")
        self.assertIsNone(calls["use_public_import"].target_id)
        self.assertNotIn(b'"alias": "private-code"', render_index_json(index))

    def test_conditional_boundary_import_is_redacted_conservatively(self) -> None:
        source = source_snapshot(
            "service.py",
            (
                b"def choose(use_private):\n"
                b"    if use_private:\n"
                b"        from private_zone import HiddenClient as service\n"
                b"    else:\n"
                b"        def service():\n"
                b"            return 'public'\n"
                b"    def run():\n"
                b"        return service()\n"
                b"    return run\n"
            ),
        )
        boundary = BoundaryData(
            alias="private-service",
            description="Approved private service",
            path="private_zone.py",
        )

        index = build_index(source, extract_structures(source), config(boundary))
        run = next(node for node in index.nodes if node.qualified_name == "choose.run")
        call = next(
            edge for edge in index.edges if edge.source_id == run.id and edge.kind == "call"
        )
        rendered = render_index_json(index)

        self.assertEqual(
            call.target,
            BoundaryPlaceholder("private-service", "Approved private service"),
        )
        self.assertIsNone(call.target_id)
        for forbidden in (b"private_zone", b"HiddenClient"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, rendered)

    def test_try_boundary_import_is_redacted_conservatively(self) -> None:
        source = source_snapshot(
            "service.py",
            (
                b"def choose():\n"
                b"    try:\n"
                b"        from private_zone import HiddenClient as service\n"
                b"    except ImportError:\n"
                b"        def service():\n"
                b"            return 'public'\n"
                b"    def run():\n"
                b"        return service()\n"
                b"    return run\n"
            ),
        )
        boundary = BoundaryData(
            alias="private-service",
            description="Approved private service",
            path="private_zone.py",
        )

        index = build_index(source, extract_structures(source), config(boundary))
        run = next(node for node in index.nodes if node.qualified_name == "choose.run")
        call = next(
            edge for edge in index.edges if edge.source_id == run.id and edge.kind == "call"
        )
        rendered = render_index_json(index)

        self.assertEqual(
            call.target,
            BoundaryPlaceholder("private-service", "Approved private service"),
        )
        self.assertIsNone(call.target_id)
        for forbidden in (b"private_zone", b"HiddenClient"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, rendered)

    def test_later_rebinding_does_not_hide_a_boundary_possible_for_a_closure(self) -> None:
        source = source_snapshot(
            "service.py",
            (
                b"def choose():\n"
                b"    from private_zone import HiddenClient as service\n"
                b"    def run():\n"
                b"        return service()\n"
                b"    run()\n"
                b"    def service():\n"
                b"        return 'public'\n"
                b"    return run\n"
            ),
        )
        boundary = BoundaryData(
            alias="private-service",
            description="Approved private service",
            path="private_zone.py",
        )

        index = build_index(source, extract_structures(source), config(boundary))
        run = next(node for node in index.nodes if node.qualified_name == "choose.run")
        call = next(
            edge for edge in index.edges if edge.source_id == run.id and edge.kind == "call"
        )

        self.assertEqual(
            call.target,
            BoundaryPlaceholder("private-service", "Approved private service"),
        )
        self.assertIsNone(call.target_id)
        self.assertNotIn(b"private_zone", render_index_json(index))

    def test_conditional_class_and_global_bindings_fall_back_to_a_boundary(self) -> None:
        source = source_snapshot(
            "service.py",
            (
                b"import private_zone as backend\n"
                b"def choose(flag):\n"
                b"    global backend\n"
                b"    if flag:\n"
                b"        import public_zone as backend\n"
                b"    def run():\n"
                b"        return backend.HiddenClient()\n"
                b"    return run\n"
                b"class Service:\n"
                b"    if ENABLE_PUBLIC:\n"
                b"        import public_zone as backend\n"
                b"    backend.HiddenClient()\n"
            ),
        )
        boundary = BoundaryData(
            alias="private-service",
            description="Approved private service",
            path="private_zone.py",
        )

        index = build_index(source, extract_structures(source), config(boundary))
        nodes = {node.qualified_name: node for node in index.nodes}

        for qualified_name in ("choose.run", "Service"):
            with self.subTest(qualified_name=qualified_name):
                call = next(
                    edge
                    for edge in index.edges
                    if edge.source_id == nodes[qualified_name].id and edge.kind == "call"
                )
                self.assertEqual(
                    call.target,
                    BoundaryPlaceholder("private-service", "Approved private service"),
                )
                self.assertIsNone(call.target_id)
        rendered = render_index_json(index)
        for forbidden in (b"private_zone", b"HiddenClient"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, rendered)

    def test_class_declarations_change_the_binding_seen_by_methods(self) -> None:
        source = source_snapshot(
            "service.py",
            (
                b"import public_zone as module_backend\n"
                b"class GlobalService:\n"
                b"    global module_backend\n"
                b"    import private_zone as module_backend\n"
                b"    def run(self):\n"
                b"        return module_backend.HiddenClient()\n"
                b"def make_service():\n"
                b"    import public_zone as closure_backend\n"
                b"    class NonlocalService:\n"
                b"        nonlocal closure_backend\n"
                b"        import private_zone as closure_backend\n"
                b"        def run(self):\n"
                b"            return closure_backend.HiddenClient()\n"
                b"    return NonlocalService\n"
            ),
        )
        boundary = BoundaryData(
            alias="private-service",
            description="Approved private service",
            path="private_zone.py",
        )

        index = build_index(source, extract_structures(source), config(boundary))
        nodes = {node.qualified_name: node for node in index.nodes}

        for qualified_name in ("GlobalService.run", "make_service.NonlocalService.run"):
            with self.subTest(qualified_name=qualified_name):
                call = next(
                    edge
                    for edge in index.edges
                    if edge.source_id == nodes[qualified_name].id and edge.kind == "call"
                )
                self.assertEqual(
                    call.target,
                    BoundaryPlaceholder("private-service", "Approved private service"),
                )
                self.assertIsNone(call.target_id)
        rendered = render_index_json(index)
        for forbidden in (b"private_zone", b"HiddenClient"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, rendered)

    def test_deferred_declaration_imports_remain_possible_boundaries(self) -> None:
        cases = (
            (
                b"import public_zone as backend\n"
                b"def configure():\n"
                b"    global backend\n"
                b"    import private_zone as backend\n"
                b"import public_zone as backend\n"
                b"configure()\n"
                b"def run():\n"
                b"    return backend.HiddenClient()\n",
                "run",
            ),
            (
                b"def outer():\n"
                b"    import public_zone as backend\n"
                b"    def configure():\n"
                b"        nonlocal backend\n"
                b"        import private_zone as backend\n"
                b"    import public_zone as backend\n"
                b"    configure()\n"
                b"    def run():\n"
                b"        return backend.HiddenClient()\n"
                b"    return run\n",
                "outer.run",
            ),
        )
        boundary = BoundaryData(
            alias="private-service",
            description="Approved private service",
            path="private_zone.py",
        )

        for content, qualified_name in cases:
            with self.subTest(qualified_name=qualified_name):
                source = source_snapshot("service.py", content)
                index = build_index(source, extract_structures(source), config(boundary))
                node = next(node for node in index.nodes if node.qualified_name == qualified_name)
                call = next(
                    edge
                    for edge in index.edges
                    if edge.source_id == node.id and edge.kind == "call"
                )

                self.assertEqual(
                    call.target,
                    BoundaryPlaceholder("private-service", "Approved private service"),
                )
                self.assertIsNone(call.target_id)
                rendered = render_index_json(index)
                for forbidden in (b"private_zone", b"HiddenClient"):
                    self.assertNotIn(forbidden, rendered)

    def test_deferred_import_without_an_outer_binding_falls_back_to_boundary(self) -> None:
        source = source_snapshot(
            "service.py",
            (
                b"def configure():\n"
                b"    global secret\n"
                b"    import public_api as secret\n"
                b"def run():\n"
                b"    return secret.Hidden()\n"
            ),
        )
        boundary = BoundaryData(
            alias="private-service",
            description="Approved private service",
            path="secret.py",
        )

        index = build_index(source, extract_structures(source), config(boundary))
        run = next(node for node in index.nodes if node.qualified_name == "run")
        call = next(
            edge for edge in index.edges if edge.source_id == run.id and edge.kind == "call"
        )

        self.assertEqual(
            call.target,
            BoundaryPlaceholder("private-service", "Approved private service"),
        )
        self.assertIsNone(call.target_id)
        self.assertNotIn(b'"target": "secret.Hidden"', render_index_json(index))

    def test_projected_import_does_not_cross_duplicate_scope_occurrences(self) -> None:
        source = source_snapshot(
            "service.py",
            (
                b"def outer():\n"
                b"    selected = None\n"
                b"    class Configure:\n"
                b"        nonlocal selected\n"
                b"        import private_zone as selected\n"
                b"    return Configure\n"
                b"def outer():\n"
                b"    import public_zone as selected\n"
                b"    def run():\n"
                b"        return selected.send()\n"
                b"    return run\n"
            ),
        )
        boundary = BoundaryData(
            alias="private-service",
            description="Approved private service",
            path="private_zone.py",
        )

        index = build_index(source, extract_structures(source), config(boundary))
        run = next(node for node in index.nodes if node.qualified_name == "outer.run")
        call = next(
            edge for edge in index.edges if edge.source_id == run.id and edge.kind == "call"
        )

        self.assertEqual(call.target, "public_zone.send")
        self.assertIsNone(call.target_id)


if __name__ == "__main__":
    unittest.main()
