from __future__ import annotations

import hashlib
import io
import unittest

from silobrief.boundary_placeholders import BoundaryPlaceholder
from silobrief.index import IndexData, IndexEdge, IndexNode, NodeKind, NodeTokens, build_index
from silobrief.python_structure import extract_structures
from silobrief.review import DisclosureChoices, ReviewNode, ReviewSelection
from silobrief.source_review import SourceReviewError, review_source_disclosure
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
