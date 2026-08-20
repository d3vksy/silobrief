from __future__ import annotations

import hashlib
import io
import unittest

from silobrief.boundary_placeholders import BoundaryPlaceholder
from silobrief.index import (
    BoundaryDisclosure,
    IndexData,
    IndexEdge,
    IndexNode,
    NodeKind,
    NodeTokens,
    build_index,
    render_index_json,
)
from silobrief.python_structure import extract_structures
from silobrief.review import DisclosureChoices, ReviewNode, ReviewSelection
from silobrief.source_excerpts import SourceExcerpt
from silobrief.source_review import SourceReviewError, _show_candidate, review_source_disclosure
from silobrief.sources import SourceFile, SourceSnapshot
from silobrief.state import DEFAULT_EXCLUDES, BoundaryData, ConfigData


class TtyBuffer(io.StringIO):
    def __init__(self, value: str = "", *, tty: bool = True) -> None:
        super().__init__(value)
        self.tty = tty

    def isatty(self) -> bool:
        return self.tty


TOKENS = NodeTokens(path=(), symbol=(), imports=(), comments=(), docstrings=())
FIELDS = DisclosureChoices(False, False, False, False, False)


def node(node_id: str, path: str, kind: NodeKind, qualified_name: str) -> IndexNode:
    return IndexNode(
        id=node_id,
        kind=kind,
        name=qualified_name.rsplit(".", 1)[-1],
        qualified_name=qualified_name,
        path=path,
        tokens=TOKENS,
    )


def review_node(value: IndexNode) -> ReviewNode:
    return ReviewNode(value.id, value.path, value.kind, value.name, value.qualified_name)


def source_file(path: str, content: bytes) -> SourceFile:
    return SourceFile(path, content, hashlib.sha256(content).hexdigest())


def snapshot(*files: SourceFile) -> SourceSnapshot:
    return SourceSnapshot(files, (), "snapshot")


def index(*nodes: IndexNode, edges: tuple[IndexEdge, ...] = ()) -> IndexData:
    return IndexData("a" * 64, edges, 1, nodes, "b" * 64, False)


class SourceReviewTests(unittest.TestCase):
    def test_source_preview_escapes_controls_without_changing_layout(self) -> None:
        osc = "\x1b]52;c;Y2xpcGJvYXJk\x07"
        csi = "\x1b[2J"
        excerpt = SourceExcerpt(
            path=f"src/{osc}\nforged.py",
            kind="function",
            qualified_name=f"run{csi}",
            start_line=1,
            end_line=3,
            content=(f'def run():\n\t# clipboard {osc}\n\treturn "cursor {csi}\x9b31m\x7f"\n'),
        )
        output = TtyBuffer()

        _show_candidate(excerpt, (f"alias{osc}",), output, "en")

        visible = output.getvalue()
        self.assertNotIn(osc, visible)
        self.assertNotIn(csi, visible)
        self.assertIn("src/\\x1b]52;c;Y2xpcGJvYXJk\\x07\\nforged.py", visible)
        self.assertIn("def run():\n\t# clipboard ", visible)
        self.assertIn("\\x1b[2J\\x9b31m\\x7f", visible)
        self.assertIn(osc, excerpt.content)

    def test_reviews_only_explicit_function_and_defaults_to_no(self) -> None:
        module = node("module", "service.py", "module", "service")
        selected = node("run", "service.py", "function", "run")
        expanded = node("helper", "helper.py", "function", "helper")
        source = snapshot(
            source_file("service.py", b"def run():\n    return 1\n"),
            source_file("helper.py", b"def helper():\n    return 2\n"),
        )
        selection = ReviewSelection(
            (review_node(module), review_node(selected)),
            (review_node(expanded),),
            FIELDS,
        )
        output = TtyBuffer()

        approved = review_source_disclosure(
            index(module, selected, expanded),
            source,
            selection,
            input_stream=TtyBuffer("\n"),
            output_stream=output,
        )

        self.assertEqual(approved, ())
        visible = output.getvalue()
        self.assertIn("def run", visible)
        self.assertNotIn("def helper", visible)
        self.assertNotIn("module service", visible)

    def test_requires_expose_for_static_boundary_reference(self) -> None:
        function = node("run", "service.py", "function", "run")
        placeholder = BoundaryPlaceholder("delivery-boundary", "Private delivery adapter")
        source = snapshot(
            source_file(
                "service.py",
                b"def run():\n    return deliver_internal()\n",
            )
        )
        selection = ReviewSelection((review_node(function),), (), FIELDS)
        source_index = index(
            function,
            edges=(IndexEdge("run", "call", placeholder, None),),
        )

        declined = review_source_disclosure(
            source_index,
            source,
            selection,
            input_stream=TtyBuffer("y\nnot-expose\n"),
            output_stream=TtyBuffer(),
        )
        approved = review_source_disclosure(
            source_index,
            source,
            selection,
            input_stream=TtyBuffer("y\nEXPOSE\n"),
            output_stream=TtyBuffer(),
        )

        self.assertEqual(declined, ())
        self.assertEqual(len(approved), 1)
        self.assertEqual(approved[0].boundary_aliases, ("delivery-boundary",))
        self.assertIn("deliver_internal", approved[0].content)

    def test_requires_expose_for_boundary_names_in_definition_headers(self) -> None:
        content = (
            b"from private_zone import decorate, SecretType, make_default, Base, meta\n"
            b"@decorate\n"
            b"def run(value: SecretType = make_default()) -> SecretType:\n"
            b"    return value\n"
            b"@decorate\n"
            b"class Service(Base, metaclass=meta):\n"
            b"    pass\n"
            b"class Outer:\n"
            b"    @decorate\n"
            b"    def method(self, value: SecretType = make_default()) -> SecretType:\n"
            b"        return value\n"
            b"    def host(self):\n"
            b"        @decorate\n"
            b"        def inner(value: SecretType = make_default()):\n"
            b"            return value\n"
            b"        return inner()\n"
        )
        source = snapshot(source_file("service.py", content))
        source_index = build_index(
            source,
            extract_structures(source),
            ConfigData(
                boundaries=[
                    BoundaryData(
                        alias="private-service",
                        description="Approved private service",
                        path="private_zone.py",
                    )
                ],
                default_excludes=list(DEFAULT_EXCLUDES),
                schema_version=1,
            ),
        )
        nodes = {node.qualified_name: node for node in source_index.nodes}
        placeholder = BoundaryPlaceholder("private-service", "Approved private service")

        self.assertEqual(
            set(source_index.boundary_disclosures),
            {
                BoundaryDisclosure(nodes["Service"].id, placeholder),
                BoundaryDisclosure(nodes["Outer.host.inner"].id, placeholder),
                BoundaryDisclosure(nodes["Outer.method"].id, placeholder),
                BoundaryDisclosure(nodes["run"].id, placeholder),
            },
        )
        module = next(node for node in source_index.nodes if node.kind == "module")
        self.assertTrue(
            any(
                edge.source_id == module.id and isinstance(edge.target, BoundaryPlaceholder)
                for edge in source_index.edges
            )
        )
        self.assertFalse(
            any(
                edge.source_id in {nodes["run"].id, nodes["Service"].id}
                and isinstance(edge.target, BoundaryPlaceholder)
                for edge in source_index.edges
            )
        )
        encoded = render_index_json(source_index)
        for private_name in (b"private_zone", b"SecretType", b"make_default"):
            self.assertNotIn(private_name, encoded)

        for qualified_name in ("run", "Service", "Outer.method", "Outer.host.inner"):
            with self.subTest(qualified_name=qualified_name):
                selection = ReviewSelection((review_node(nodes[qualified_name]),), (), FIELDS)
                output = TtyBuffer()
                declined = review_source_disclosure(
                    source_index,
                    source,
                    selection,
                    input_stream=TtyBuffer("y\nnot-expose\n"),
                    output_stream=output,
                )
                approved = review_source_disclosure(
                    source_index,
                    source,
                    selection,
                    input_stream=TtyBuffer("y\nEXPOSE\n"),
                    output_stream=TtyBuffer(),
                )

                self.assertEqual(declined, ())
                self.assertIn("Boundary aliases: private-service", output.getvalue())
                self.assertIn("Type exactly EXPOSE", output.getvalue())
                self.assertEqual(len(approved), 1)
                self.assertEqual(approved[0].boundary_aliases, ("private-service",))

    def test_requires_expose_for_deferred_header_annotations(self) -> None:
        content = (
            b"from private_zone import SecretType\n"
            b"def quoted(value: 'SecretType') -> 'list[SecretType]':\n"
            b"    return value\n"
            b"def commented(\n"
            b"    value,  # type: SecretType\n"
            b"):\n"
            b"    # type: (SecretType) -> SecretType\n"
            b"    return value\n"
            b"def public(value: 'PublicType') -> 'PublicType':\n"
            b"    return value\n"
        )
        source = snapshot(source_file("service.py", content))
        source_index = build_index(
            source,
            extract_structures(source),
            ConfigData(
                boundaries=[
                    BoundaryData(
                        alias="private-service",
                        description="Approved private service",
                        path="private_zone.py",
                    )
                ],
                default_excludes=list(DEFAULT_EXCLUDES),
                schema_version=1,
            ),
        )
        nodes = {node.qualified_name: node for node in source_index.nodes}
        placeholder = BoundaryPlaceholder("private-service", "Approved private service")

        self.assertEqual(
            set(source_index.boundary_disclosures),
            {
                BoundaryDisclosure(nodes["quoted"].id, placeholder),
                BoundaryDisclosure(nodes["commented"].id, placeholder),
            },
        )
        self.assertFalse(any(edge.target == "PublicType" for edge in source_index.edges))
        encoded = render_index_json(source_index)
        for private_name in (b"private_zone", b"SecretType"):
            self.assertNotIn(private_name, encoded)

        for qualified_name in ("quoted", "commented"):
            with self.subTest(qualified_name=qualified_name):
                output = TtyBuffer()
                declined = review_source_disclosure(
                    source_index,
                    source,
                    ReviewSelection((review_node(nodes[qualified_name]),), (), FIELDS),
                    input_stream=TtyBuffer("y\nnot-expose\n"),
                    output_stream=output,
                )
                approved = review_source_disclosure(
                    source_index,
                    source,
                    ReviewSelection((review_node(nodes[qualified_name]),), (), FIELDS),
                    input_stream=TtyBuffer("y\nEXPOSE\n"),
                    output_stream=TtyBuffer(),
                )

                self.assertEqual(declined, ())
                self.assertIn("Boundary aliases: private-service", output.getvalue())
                self.assertIn("Type exactly EXPOSE", output.getvalue())
                self.assertEqual(len(approved), 1)
                self.assertEqual(approved[0].boundary_aliases, ("private-service",))

        output = TtyBuffer()
        approved = review_source_disclosure(
            source_index,
            source,
            ReviewSelection((review_node(nodes["public"]),), (), FIELDS),
            input_stream=TtyBuffer("y\n"),
            output_stream=output,
        )

        self.assertEqual(len(approved), 1)
        self.assertEqual(approved[0].boundary_aliases, ())
        self.assertNotIn("Type exactly EXPOSE", output.getvalue())

    def test_distinguishes_class_and_function_header_owners_with_the_same_name(self) -> None:
        content = (
            b"from private_zone import decorate\n"
            b"class Header:\n"
            b"    pass\n"
            b"@decorate\n"
            b"def Header():\n"
            b"    return 1\n"
            b"def Reverse():\n"
            b"    return 2\n"
            b"@decorate\n"
            b"class Reverse:\n"
            b"    pass\n"
            b"class Outer:\n"
            b"    pass\n"
            b"def Outer():\n"
            b"    @decorate\n"
            b"    def inner():\n"
            b"        return 3\n"
            b"    return inner\n"
            b"def ClassOuter():\n"
            b"    return 4\n"
            b"class ClassOuter:\n"
            b"    @decorate\n"
            b"    def inner(self):\n"
            b"        return 5\n"
        )
        source = snapshot(source_file("service.py", content))
        source_index = build_index(
            source,
            extract_structures(source),
            ConfigData(
                boundaries=[
                    BoundaryData(
                        alias="private-service",
                        description="Approved private service",
                        path="private_zone.py",
                    )
                ],
                default_excludes=list(DEFAULT_EXCLUDES),
                schema_version=1,
            ),
        )
        nodes = {(node.kind, node.qualified_name): node for node in source_index.nodes}
        placeholder = BoundaryPlaceholder("private-service", "Approved private service")

        self.assertEqual(
            set(source_index.boundary_disclosures),
            {
                BoundaryDisclosure(nodes[("function", "Header")].id, placeholder),
                BoundaryDisclosure(nodes[("class", "Reverse")].id, placeholder),
                BoundaryDisclosure(nodes[("function", "Outer.inner")].id, placeholder),
                BoundaryDisclosure(nodes[("function", "ClassOuter.inner")].id, placeholder),
            },
        )
        module = next(node for node in source_index.nodes if node.kind == "module")
        self.assertEqual(
            {edge.source_id for edge in source_index.edges if edge.target == placeholder},
            {
                module.id,
                nodes[("function", "Outer")].id,
                nodes[("class", "ClassOuter")].id,
            },
        )
        contains = {
            (edge.source_id, edge.target_id)
            for edge in source_index.edges
            if edge.kind == "contains"
        }
        self.assertIn(
            (nodes[("function", "Outer")].id, nodes[("function", "Outer.inner")].id),
            contains,
        )
        self.assertIn(
            (
                nodes[("class", "ClassOuter")].id,
                nodes[("function", "ClassOuter.inner")].id,
            ),
            contains,
        )
        self.assertNotIn(
            (nodes[("class", "Outer")].id, nodes[("function", "Outer.inner")].id),
            contains,
        )
        self.assertNotIn(
            (
                nodes[("function", "ClassOuter")].id,
                nodes[("function", "ClassOuter.inner")].id,
            ),
            contains,
        )
        encoded = render_index_json(source_index)
        for private_name in (b"private_zone", b"decorate"):
            self.assertNotIn(private_name, encoded)

        protected = (
            nodes[("function", "Header")],
            nodes[("class", "Reverse")],
            nodes[("function", "Outer")],
            nodes[("class", "ClassOuter")],
        )
        for selected in protected:
            with self.subTest(protected=(selected.kind, selected.qualified_name)):
                output = TtyBuffer()
                approved = review_source_disclosure(
                    source_index,
                    source,
                    ReviewSelection((review_node(selected),), (), FIELDS),
                    input_stream=TtyBuffer("y\nnot-expose\n"),
                    output_stream=output,
                )

                self.assertEqual(approved, ())
                self.assertIn("Type exactly EXPOSE", output.getvalue())

        safe = (
            nodes[("class", "Header")],
            nodes[("function", "Reverse")],
            nodes[("class", "Outer")],
            nodes[("function", "ClassOuter")],
        )
        for selected in safe:
            with self.subTest(safe=(selected.kind, selected.qualified_name)):
                output = TtyBuffer()
                approved = review_source_disclosure(
                    source_index,
                    source,
                    ReviewSelection((review_node(selected),), (), FIELDS),
                    input_stream=TtyBuffer("y\n"),
                    output_stream=output,
                )

                self.assertEqual(len(approved), 1)
                self.assertEqual(approved[0].boundary_aliases, ())
                self.assertNotIn("Type exactly EXPOSE", output.getvalue())

    def test_does_not_apply_unrelated_header_disclosure_to_another_function(self) -> None:
        content = (
            b"from private_zone import decorate\n"
            b"@decorate\n"
            b"def protected():\n"
            b"    return 1\n"
            b"def public():\n"
            b"    return 2\n"
        )
        source = snapshot(source_file("service.py", content))
        source_index = build_index(
            source,
            extract_structures(source),
            ConfigData(
                boundaries=[
                    BoundaryData(
                        alias="private-service",
                        description="Approved private service",
                        path="private_zone.py",
                    )
                ],
                default_excludes=list(DEFAULT_EXCLUDES),
                schema_version=1,
            ),
        )
        public = next(node for node in source_index.nodes if node.qualified_name == "public")
        output = TtyBuffer()

        approved = review_source_disclosure(
            source_index,
            source,
            ReviewSelection((review_node(public),), (), FIELDS),
            input_stream=TtyBuffer("y\n"),
            output_stream=output,
        )

        self.assertEqual(len(approved), 1)
        self.assertEqual(approved[0].boundary_aliases, ())
        self.assertIn("Boundary aliases: none", output.getvalue())
        self.assertNotIn("Type exactly EXPOSE", output.getvalue())

    def test_class_approval_absorbs_method_and_its_boundary_alias(self) -> None:
        owner = node("owner", "service.py", "class", "Service")
        method = node("method", "service.py", "function", "Service.run")
        placeholder = BoundaryPlaceholder("delivery-boundary", "Private delivery adapter")
        source = snapshot(
            source_file(
                "service.py",
                b"class Service:\n    def run(self):\n        return deliver_internal()\n",
            )
        )
        selection = ReviewSelection((review_node(owner), review_node(method)), (), FIELDS)
        source_index = index(
            owner,
            method,
            edges=(
                IndexEdge("owner", "contains", "Service.run", "method"),
                IndexEdge("method", "call", placeholder, None),
            ),
        )

        approved = review_source_disclosure(
            source_index,
            source,
            selection,
            input_stream=TtyBuffer("y\nEXPOSE\n"),
            output_stream=TtyBuffer(),
        )

        self.assertEqual(len(approved), 1)
        self.assertEqual(approved[0].qualified_name, "Service")
        self.assertEqual(approved[0].boundary_aliases, ("delivery-boundary",))

    def test_reviews_every_span_for_a_repeated_definition(self) -> None:
        value = node("value", "models.py", "function", "Item.value")
        source = snapshot(
            source_file(
                "models.py",
                (
                    b"class Item:\n"
                    b"    @property\n"
                    b"    def value(self):\n"
                    b"        return self._value\n"
                    b"\n"
                    b"    @value.setter\n"
                    b"    def value(self, new):\n"
                    b"        self._value = new\n"
                ),
            )
        )
        output = TtyBuffer()

        approved = review_source_disclosure(
            index(value),
            source,
            ReviewSelection((review_node(value),), (), FIELDS),
            input_stream=TtyBuffer("y\ny\n"),
            output_stream=output,
        )

        self.assertEqual(len(approved), 2)
        self.assertIn("@property", approved[0].content)
        self.assertIn("@value.setter", approved[1].content)
        self.assertEqual(output.getvalue().count("Source candidate:"), 2)

    def test_deferred_boundary_binding_requires_expose(self) -> None:
        source = snapshot(
            source_file(
                "service.py",
                (
                    b"import public_zone as backend\n"
                    b"def configure():\n"
                    b"    global backend\n"
                    b"    import private_zone as backend\n"
                    b"import public_zone as backend\n"
                    b"configure()\n"
                    b"def run():\n"
                    b"    return backend.HiddenClient()\n"
                ),
            )
        )
        source_index = build_index(
            source,
            extract_structures(source),
            ConfigData(
                boundaries=[
                    BoundaryData(
                        alias="private-service",
                        description="Approved private service",
                        path="private_zone.py",
                    )
                ],
                default_excludes=list(DEFAULT_EXCLUDES),
                schema_version=1,
            ),
        )
        run = next(node for node in source_index.nodes if node.qualified_name == "run")
        selection = ReviewSelection((review_node(run),), (), FIELDS)

        declined = review_source_disclosure(
            source_index,
            source,
            selection,
            input_stream=TtyBuffer("y\nnot-expose\n"),
            output_stream=TtyBuffer(),
        )
        approved = review_source_disclosure(
            source_index,
            source,
            selection,
            input_stream=TtyBuffer("y\nEXPOSE\n"),
            output_stream=TtyBuffer(),
        )

        self.assertEqual(declined, ())
        self.assertEqual(len(approved), 1)
        self.assertEqual(approved[0].boundary_aliases, ("private-service",))

    def test_parse_failure_does_not_remove_valid_candidate(self) -> None:
        broken = node("broken", "bad.py", "function", "broken")
        valid = node("valid", "good.py", "function", "valid")
        source = snapshot(
            source_file("bad.py", b"def broken(:  # PARSE_CANARY\n"),
            source_file("good.py", b"def valid():\n    return 1\n"),
        )
        output = TtyBuffer()

        approved = review_source_disclosure(
            index(broken, valid),
            source,
            ReviewSelection((review_node(broken), review_node(valid)), (), FIELDS),
            input_stream=TtyBuffer("y\n"),
            output_stream=output,
        )

        self.assertEqual([item.qualified_name for item in approved], ["valid"])
        self.assertIn("bad.py", output.getvalue())
        self.assertNotIn("PARSE_CANARY", output.getvalue())

    def test_skips_approved_excerpt_that_exceeds_limit(self) -> None:
        function = node("huge", "huge.py", "function", "huge")
        content = b"def huge():\n" + (b"    value = 1\n" * 4_000)
        output = TtyBuffer()

        approved = review_source_disclosure(
            index(function),
            snapshot(source_file("huge.py", content)),
            ReviewSelection((review_node(function),), (), FIELDS),
            input_stream=TtyBuffer("y\n"),
            output_stream=output,
        )

        self.assertEqual(approved, ())
        self.assertIn("skipped", output.getvalue())
        self.assertIn("4001 lines", output.getvalue())

    def test_rejects_non_interactive_streams(self) -> None:
        function = node("run", "service.py", "function", "run")
        source = snapshot(source_file("service.py", b"def run():\n    pass\n"))
        selection = ReviewSelection((review_node(function),), (), FIELDS)

        for input_tty, output_tty in ((False, True), (True, False)):
            with self.subTest(input_tty=input_tty, output_tty=output_tty):
                with self.assertRaisesRegex(SourceReviewError, "interactive terminal"):
                    review_source_disclosure(
                        index(function),
                        source,
                        selection,
                        input_stream=TtyBuffer(tty=input_tty),
                        output_stream=TtyBuffer(tty=output_tty),
                    )


if __name__ == "__main__":
    unittest.main()
