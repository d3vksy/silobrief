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
            IndexEdge("root-id", "import", "urllib3", None),
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


APPROVED_INPUT = "1\nsrc/direct.py\n\nsrc/direct.py\n\ny\ny\ny\ny\ny\n"


def disclosure_counts(rendered: RenderedBrief) -> tuple[int, int, int, int, int]:
    value = rendered.disclosure
    return (
        value.relative_paths,
        value.symbol_names,
        value.public_dependencies,
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
        self.assertIn("path=1", visible)
        self.assertIn("connected=1", visible)
        hidden_values = (
            "source-body-canary|internal-real-name|src/direct.py|src/second.py|"
            "second-hop-canary|unselected-note-canary|root-id"
        )
        for hidden in hidden_values.split("|"):
            self.assertNotIn(hidden, visible + rendered.markdown)

    def test_allows_every_disclosure_field_to_be_declined(self) -> None:
        rendered = review_brief(
            "retry",
            source_index(),
            source_notes(),
            input_stream=TtyBuffer("1\n\n\nn\nn\nn\nn\nn\n"),
            output_stream=TtyBuffer(),
        )

        self.assertEqual(disclosure_counts(rendered), (0, 0, 0, 0, 0))
        self.assertEqual(rendered.markdown.count("- 없음"), 5)

    def test_rejects_invalid_or_empty_review_input(self) -> None:
        cases = (
            (" ", "", "request"),
            ("absent", "", "candidate"),
            ("retry", "2\n\n\n", "candidate number"),
            ("retry", "1\n\n\nY\n", "y or n"),
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
