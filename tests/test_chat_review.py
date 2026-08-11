from __future__ import annotations

import io
import unittest
from dataclasses import replace

from silobrief.boundary_placeholders import BoundaryPlaceholder
from silobrief.chat_review import ChatReviewError, review_brief
from silobrief.index import IndexData, IndexEdge, IndexNode, NodeKind, NodeTokens
from silobrief.renderer import RenderedBrief
from silobrief.state import HumanNoteData, NotesData


class TtyBuffer(io.StringIO):
    def __init__(self, value: str = "", *, tty: bool = True) -> None:
        super().__init__(value)
        self.tty = tty

    def isatty(self) -> bool:
        return self.tty


EMPTY_TOKENS = NodeTokens(path=(), symbol=(), imports=(), comments=(), docstrings=())


def node(
    node_id: str, path: str, kind: NodeKind, name: str, qualified_name: str | None = None
) -> IndexNode:
    return IndexNode(
        id=node_id,
        kind=kind,
        name=name,
        qualified_name=qualified_name or name,
        path=path,
        tokens=EMPTY_TOKENS,
    )


def source_index() -> IndexData:
    root = replace(
        node("root-id", "src/service.py", "module", "service"),
        tokens=NodeTokens(
            path=("retry",),
            symbol=(),
            imports=("internal-real-name",),
            comments=("source-body-canary",),
            docstrings=(),
        ),
    )
    neighbor = node("neighbor-id", "src/helper.py", "function", "run", "helper.run")
    direct = node("direct-id", "src/direct.py", "module", "direct")
    second = node("second-id", "src/second.py", "function", "second")
    return IndexData(
        config_digest="a" * 64,
        edges=(
            IndexEdge("root-id", "call", "helper.run", "neighbor-id"),
            IndexEdge("neighbor-id", "call", "second", "second-id"),
            IndexEdge("root-id", "import", "helper.run", "neighbor-id"),
            IndexEdge("root-id", "import", "urllib3", None),
            IndexEdge("root-id", "import", ".models.SyncResult", None),
            IndexEdge("neighbor-id", "import", "json", None),
            IndexEdge("second-id", "import", "second-hop-canary", None),
            IndexEdge(
                "root-id",
                "import",
                BoundaryPlaceholder("transport", "Public transport adapter"),
                None,
            ),
        ),
        index_version=1,
        nodes=(root, neighbor, direct, second),
        source_digest="b" * 64,
        stale=False,
    )


def source_notes() -> NotesData:
    return NotesData(
        notes=[
            HumanNoteData(comment="Use Python 3.10", id="note-" + "1" * 64, path="src"),
            HumanNoteData(
                comment="Keep the retry policy public", id="note-" + "2" * 64, path="src/service.py"
            ),
            HumanNoteData(
                comment="unselected-note-canary", id="note-" + "3" * 64, path="src/second.py"
            ),
        ],
        notes_version=1,
    )


APPROVED_INPUT = "y\n1\nr1\nsrc/direct.py\n\n\nsrc/direct.py\n\ny\ny\ny\ny\ny\n"


def disclosure_counts(rendered: RenderedBrief) -> tuple[int, int, int, int, int]:
    value = rendered.disclosure
    return (
        value.relative_paths,
        value.symbol_names,
        value.public_imports,
        value.human_notes,
        value.boundary_aliases,
    )


class ChatReviewTests(unittest.TestCase):
    def test_reviews_one_step_and_renders_only_approved_context(self) -> None:
        index = source_index()
        output = TtyBuffer()

        rendered = review_brief(
            "retry",
            index,
            source_notes(),
            input_stream=TtyBuffer(APPROVED_INPUT),
            output_stream=output,
        )
        reordered = review_brief(
            "retry",
            replace(index, nodes=tuple(reversed(index.nodes)), edges=tuple(reversed(index.edges))),
            source_notes(),
            input_stream=TtyBuffer(APPROVED_INPUT),
            output_stream=TtyBuffer(),
        )

        self.assertEqual(rendered, reordered)
        self.assertEqual(disclosure_counts(rendered), (2, 2, 2, 2, 1))
        approved_values = (
            "src/service.py|src/helper.py|helper.run|urllib3|json|Use Python 3.10|"
            "Keep the retry policy public|transport|Public transport adapter"
        )
        for approved in approved_values.split("|"):
            self.assertIn(approved, rendered.markdown)

        visible = output.getvalue()
        self.assertIn("src/service.py", visible)
        self.assertIn("src/helper.py", visible)
        self.assertIn("path=retry", visible)
        self.assertIn("connections: 1", visible)
        hidden_values = (
            "source-body-canary|internal-real-name|.models.SyncResult|src/second.py|"
            "second-hop-canary|unselected-note-canary|root-id"
        )
        for hidden in hidden_values.split("|"):
            self.assertNotIn(hidden, visible + rendered.markdown)
        self.assertNotIn("src/direct.py", rendered.markdown)

    def test_related_context_requires_explicit_approval(self) -> None:
        output = TtyBuffer()

        rendered = review_brief(
            "retry",
            source_index(),
            source_notes(),
            input_stream=TtyBuffer("y\n1\n\n\ny\ny\ny\ny\ny\n"),
            output_stream=output,
        )

        visible = output.getvalue()
        self.assertIn("Related context (not selected):", visible)
        self.assertIn("r1. src/helper.py", visible)
        self.assertIn("calls, imports", visible)
        self.assertIn("src/service.py", rendered.markdown)
        self.assertNotIn("src/helper.py", rendered.markdown)
        self.assertNotIn("helper.run", rendered.markdown)
        self.assertNotIn("json", rendered.markdown)
        self.assertEqual(disclosure_counts(rendered), (1, 1, 1, 2, 1))

    def test_allows_every_disclosure_field_to_be_declined(self) -> None:
        rendered = review_brief(
            "retry",
            source_index(),
            source_notes(),
            input_stream=TtyBuffer("y\n1\n\n\nn\nn\nn\nn\nn\n"),
            output_stream=TtyBuffer(),
        )

        self.assertEqual(disclosure_counts(rendered), (0, 0, 0, 0, 0))
        self.assertEqual(rendered.markdown.count("- none"), 3)
        for title in ("사용자 작성 메모", "등록된 경계", "소스 동반 파일"):
            self.assertNotIn(f"## {title}", rendered.markdown)

    def test_recovers_from_empty_candidates_with_a_file_outline(self) -> None:
        module = node("module", "src/guided.py", "module", "guided")
        service = node("service", "src/guided.py", "class", "Service")
        method = node("method", "src/guided.py", "function", "run", "Service.run")
        helper = node("helper", "src/guided.py", "function", "helper")
        external = node("external", "src/external.py", "function", "external")
        index = IndexData(
            config_digest="a" * 64,
            edges=(
                IndexEdge("helper", "call", "external", "external"),
                IndexEdge("module", "contains", "Service", "service"),
                IndexEdge("module", "contains", "Service.run", "method"),
                IndexEdge("module", "contains", "helper", "helper"),
            ),
            index_version=1,
            nodes=(external, helper, method, module, service),
            source_digest="b" * 64,
            stale=False,
        )
        output = TtyBuffer()

        rendered = review_brief(
            "no matching terms",
            index,
            NotesData(notes=[], notes_version=1),
            input_stream=TtyBuffer("y\n\nsrc/guided.py\n1 2\n\n\ny\ny\nn\nn\nn\n"),
            output_stream=output,
        )
        node_id_output = TtyBuffer()
        selected_by_id = review_brief(
            "no matching terms",
            index,
            NotesData(notes=[], notes_version=1),
            input_stream=TtyBuffer("y\n\nservice\nmethod\n\n\ny\ny\nn\nn\nn\n"),
            output_stream=node_id_output,
        )

        visible = output.getvalue()
        self.assertEqual(rendered, selected_by_id)
        self.assertIn("Candidates:\n- none", visible)
        self.assertIn("Symbols in `src/guided.py`:", visible)
        self.assertIn("1. class Service", visible)
        self.assertIn("2. function Service.run", visible)
        outline = visible.split("Symbols in `src/guided.py`:\n", 1)[1].split(
            "Select symbol numbers", 1
        )[0]
        self.assertNotIn("module guided", outline)
        self.assertNotIn("Symbols in", node_id_output.getvalue())
        self.assertIn("class Service", visible)
        self.assertIn("src/guided.py", rendered.markdown)
        self.assertIn("function: Service.run", rendered.markdown)
        self.assertNotIn("function: helper", rendered.markdown)
        self.assertNotIn("src/external.py", rendered.markdown)
        self.assertEqual(rendered.disclosure.symbol_names, 2)

    def test_keeps_module_when_file_outline_has_no_symbol_selection(self) -> None:
        module = node("module", "src/guided.py", "module", "guided")
        service = node("service", "src/guided.py", "class", "Service")
        helper = node("helper", "src/guided.py", "function", "helper")
        index = IndexData(
            config_digest="a" * 64,
            edges=(
                IndexEdge("module", "contains", "Service", "service"),
                IndexEdge("module", "contains", "helper", "helper"),
            ),
            index_version=1,
            nodes=(helper, module, service),
            source_digest="b" * 64,
            stale=False,
        )

        rendered = review_brief(
            "no matching terms",
            index,
            NotesData(notes=[], notes_version=1),
            input_stream=TtyBuffer("y\n\nsrc/guided.py\n\n\n\ny\ny\nn\nn\nn\n"),
            output_stream=TtyBuffer(),
        )

        self.assertIn("module: guided", rendered.markdown)
        self.assertNotIn("class: Service", rendered.markdown)
        self.assertNotIn("function: helper", rendered.markdown)
        self.assertEqual(rendered.disclosure.symbol_names, 1)

    def test_exact_path_selection_can_approve_a_related_symbol(self) -> None:
        module = node("module", "src/guided.py", "module", "guided")
        service = node("service", "src/guided.py", "class", "Service")
        helper = node("helper", "src/guided.py", "function", "helper")
        index = IndexData(
            config_digest="a" * 64,
            edges=(
                IndexEdge("module", "contains", "Service", "service"),
                IndexEdge("module", "contains", "helper", "helper"),
            ),
            index_version=1,
            nodes=(helper, module, service),
            source_digest="b" * 64,
            stale=False,
        )
        output = TtyBuffer()

        rendered = review_brief(
            "no matching terms",
            index,
            NotesData(notes=[], notes_version=1),
            input_stream=TtyBuffer("y\n\nsrc/guided.py\n\nr1\n\n\ny\ny\nn\nn\nn\n"),
            output_stream=output,
        )

        self.assertIn("r1. src/guided.py | class Service | contains", output.getvalue())
        self.assertIn("module: guided", rendered.markdown)
        self.assertIn("class: Service", rendered.markdown)
        self.assertNotIn("function: helper", rendered.markdown)

    def test_rejects_unknown_file_and_invalid_outline_number(self) -> None:
        module = node("module", "src/guided.py", "module", "guided")
        function = node("function", "src/guided.py", "function", "run")
        index = IndexData(
            config_digest="a" * 64,
            edges=(),
            index_version=1,
            nodes=(module, function),
            source_digest="b" * 64,
            stale=False,
        )
        cases = (
            ("y\n\n../secret.py\n", "not present in the current index"),
            ("y\n\nsrc/guided.py\n-1\n", "positive integers"),
            ("y\n\nsrc/guided.py\n0\n", "symbol number"),
            ("y\n\nsrc/guided.py\none\n", "positive integers"),
            ("y\n\nsrc/guided.py\n2\n", "symbol number"),
        )
        for input_text, message in cases:
            with self.subTest(message=message):
                with self.assertRaisesRegex(ChatReviewError, message):
                    review_brief(
                        "no matching terms",
                        index,
                        NotesData(notes=[], notes_version=1),
                        input_stream=TtyBuffer(input_text),
                        output_stream=TtyBuffer(),
                    )

    def test_rejects_invalid_or_empty_review_input(self) -> None:
        cases = (
            (" ", "", "request"),
            ("absent", "y\n", "start selection"),
            ("retry", "y\n2\n\n\n", "candidate number"),
            ("retry", "y\n1\nr2\n", "related candidate"),
            ("retry", "y\n1\n\n\nY\n", "y or n"),
        )
        for prompt, input_text, message in cases:
            with self.subTest(message=message):
                with self.assertRaisesRegex(ChatReviewError, message):
                    review_brief(
                        prompt,
                        source_index(),
                        source_notes(),
                        input_stream=TtyBuffer(input_text),
                        output_stream=TtyBuffer(),
                    )

    def test_requires_request_completeness_confirmation(self) -> None:
        for answer in ("\n", "n\n"):
            with self.subTest(answer=answer):
                output = TtyBuffer()
                with self.assertRaisesRegex(ChatReviewError, "completeness"):
                    review_brief(
                        "retry",
                        source_index(),
                        source_notes(),
                        input_stream=TtyBuffer(answer),
                        output_stream=output,
                    )
                self.assertNotIn("Candidates:", output.getvalue())

    def test_requires_interactive_input_and_output(self) -> None:
        for input_tty, output_tty in ((False, True), (True, False)):
            with self.subTest(input_tty=input_tty, output_tty=output_tty):
                with self.assertRaisesRegex(ChatReviewError, "interactive terminal"):
                    review_brief(
                        "retry",
                        source_index(),
                        source_notes(),
                        input_stream=TtyBuffer(APPROVED_INPUT, tty=input_tty),
                        output_stream=TtyBuffer(tty=output_tty),
                    )
