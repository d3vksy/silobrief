from __future__ import annotations

import hashlib
import io
import re
import unittest
from dataclasses import replace

from silobrief.boundary_placeholders import BoundaryPlaceholder
from silobrief.candidate_search import render_candidate_results
from silobrief.chat_review import (
    ChatReviewError,
    _boundaries,
    _public_imports,
    _show_related_candidates,
    _show_selected_context,
    _show_symbol_options,
    _source_context_ids,
    review_brief,
)
from silobrief.index import (
    BoundaryDisclosure,
    IndexData,
    IndexEdge,
    IndexNode,
    NodeKind,
    NodeTokens,
    build_index,
)
from silobrief.python_structure import extract_structures
from silobrief.ranking import RankEvidence
from silobrief.renderer import ApprovedBoundary, RenderedBrief
from silobrief.review import (
    CandidateOption,
    DisclosureChoices,
    ReviewNode,
    ReviewSelection,
    SymbolOption,
)
from silobrief.sources import SourceFile, SourceSnapshot
from silobrief.state import (
    DEFAULT_EXCLUDES,
    BoundaryData,
    ConfigData,
    HumanNoteData,
    NotesData,
)


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
            IndexEdge("root-id", "call", "urllib3.request", None),
            IndexEdge("root-id", "import", ".models.SyncResult", None),
            IndexEdge("neighbor-id", "import", "json", None),
            IndexEdge("neighbor-id", "call", "json.dumps", None),
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


def parsed_source_index() -> IndexData:
    content = (
        b"import requests as http\n"
        b"import unused_library\n"
        b"import sibling_library\n"
        b"from private_api import send\n\n"
        b"class Selected:\n"
        b"    def run(self):\n"
        b"        import requests\n"
        b"        requests.post('https://example.com')\n"
        b"        http.get('https://example.com')\n"
        b"        return send()\n\n"
        b"class Sibling:\n"
        b"    def run(self):\n"
        b"        return sibling_library.use()\n"
    )
    source = SourceFile(
        path="service.py",
        content=content,
        sha256=hashlib.sha256(content).hexdigest(),
    )
    snapshot = SourceSnapshot(files=(source,), warnings=(), digest="c" * 64)
    config = ConfigData(
        boundaries=[
            BoundaryData(
                alias="delivery-boundary",
                description="External delivery adapter",
                path="private_api",
            )
        ],
        default_excludes=list(DEFAULT_EXCLUDES),
        schema_version=1,
    )
    return build_index(snapshot, extract_structures(snapshot), config)


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
    def test_boundary_fields_include_definition_header_disclosures(self) -> None:
        placeholder = BoundaryPlaceholder("private-service", "Approved private service")
        value = IndexData(
            config_digest="a" * 64,
            edges=(),
            index_version=1,
            nodes=(node("run", "service.py", "function", "run"),),
            source_digest="b" * 64,
            stale=False,
            boundary_disclosures=(BoundaryDisclosure("run", placeholder),),
        )

        self.assertEqual(
            _boundaries(value, {"run"}),
            (ApprovedBoundary("private-service", "Approved private service"),),
        )
        self.assertEqual(_boundaries(value, set()), ())

    def test_terminal_lists_escape_untrusted_candidate_and_related_values(self) -> None:
        osc = "\x1b]52;c;Y2xpcGJvYXJk\x07"
        csi = "\x1b[2J"
        unsafe = ReviewNode(
            "unsafe",
            f"src/{csi}\r\nforged.py",
            "function",
            "run",
            f"Service.{osc}run",
            ("calls",),
        )
        evidence = RankEvidence(
            path_matches=(f"path{osc}",),
            symbol_matches=(),
            import_matches=(),
            docstring_matches=(),
            comment_matches=(),
            note_matches=("메모\x9b31m\x7f",),
            connected_nodes=1,
        )

        for color in (False, True):
            with self.subTest(color=color):
                visible = render_candidate_results(
                    (CandidateOption(1, unsafe, 9, evidence),),
                    color=color,
                )
                self.assertNotIn(osc, visible)
                self.assertNotIn(csi, visible)
                self.assertNotIn("\r\nforged.py", visible)
                self.assertIn("\\x1b]52;c;Y2xpcGJvYXJk\\x07", visible)
                self.assertIn("\\x1b[2J\\r\\nforged.py", visible)
                self.assertIn("메모\\x9b31m\\x7f", visible)
                self.assertEqual("\x1b[1m" in visible, color)
                without_application_styles = re.sub(r"\x1b\[[0-9;]*m", "", visible)
                self.assertFalse(
                    any(
                        ord(character) < 0x20
                        and character != "\n"
                        or 0x7F <= ord(character) <= 0x9F
                        for character in without_application_styles
                    )
                )

        related_output = TtyBuffer()
        _show_related_candidates((unsafe,), related_output, "en")
        _show_selected_context(
            ReviewSelection(
                (unsafe,),
                (),
                DisclosureChoices(False, False, False, False, False),
            ),
            related_output,
            "en",
        )
        _show_symbol_options(
            f"src/{osc}\nforged.py",
            (SymbolOption(1, unsafe),),
            related_output,
            "en",
        )
        related_visible = related_output.getvalue()
        self.assertNotIn(osc, related_visible)
        self.assertNotIn(csi, related_visible)
        self.assertIn("\\x1b]52;c;Y2xpcGJvYXJk\\x07", related_visible)
        self.assertIn("\\x1b[2J\\r\\nforged.py", related_visible)

    def test_selected_function_includes_only_its_used_module_import(self) -> None:
        index = parsed_source_index()

        rendered = review_brief(
            "no matching terms",
            index,
            NotesData(notes=[], notes_version=1),
            input_stream=TtyBuffer("y\n\nservice.py\n2\n\n\nn\nn\ny\nn\ny\n"),
            output_stream=TtyBuffer(),
        )
        declined = review_brief(
            "no matching terms",
            index,
            NotesData(notes=[], notes_version=1),
            input_stream=TtyBuffer("y\n\nservice.py\n2\n\n\nn\nn\nn\nn\nn\n"),
            output_stream=TtyBuffer(),
        )

        self.assertEqual(disclosure_counts(rendered), (0, 0, 1, 0, 1))
        self.assertIn("### Public imports\n\n- approved item:\n  > requests", rendered.markdown)
        self.assertIn("delivery-boundary", rendered.markdown)
        self.assertIn("External delivery adapter", rendered.markdown)
        for excluded in ("\n  > http\n", "unused_library", "sibling_library"):
            self.assertNotIn(excluded, rendered.markdown)
        self.assertEqual(disclosure_counts(declined), (0, 0, 0, 0, 0))
        self.assertNotIn("requests", declined.markdown)
        self.assertNotIn("delivery-boundary", declined.markdown)

    def test_selected_class_aggregates_descendants_without_sibling_imports(self) -> None:
        index = parsed_source_index()
        selected_id = next(node.id for node in index.nodes if node.qualified_name == "Selected")
        included_ids, enclosing_ids = _source_context_ids(index, {selected_id})
        import_source_ids = included_ids | enclosing_ids

        self.assertEqual(
            sum(
                edge.kind == "import"
                and edge.source_id in import_source_ids
                and edge.target == "requests"
                for edge in index.edges
            ),
            2,
        )
        self.assertEqual(_public_imports(index, included_ids, enclosing_ids), ("requests",))

        rendered = review_brief(
            "no matching terms",
            index,
            NotesData(notes=[], notes_version=1),
            input_stream=TtyBuffer("y\n\nservice.py\n1\n\n\nn\nn\ny\nn\ny\n"),
            output_stream=TtyBuffer(),
        )

        self.assertEqual(disclosure_counts(rendered), (0, 0, 1, 0, 1))
        self.assertIn("### Public imports\n\n- approved item:\n  > requests", rendered.markdown)
        self.assertIn("delivery-boundary", rendered.markdown)
        self.assertNotIn("unused_library", rendered.markdown)
        self.assertNotIn("sibling_library", rendered.markdown)

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
        self.assertIn("[Notice] Your prompt works best when it includes:", visible)
        self.assertIn("- how you will decide it is complete", visible)
        self.assertIn("src/service.py", visible)
        self.assertIn("src/helper.py", visible)
        self.assertIn('file path and user note contain "retry"', visible)
        self.assertIn("Directly connected items: 1", visible)
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
        self.assertIn("Other code connected to your selection (optional):", visible)
        self.assertIn("[r1] function helper.run", visible)
        self.assertIn("File: src/helper.py", visible)
        self.assertIn("the selected code calls this function", visible)
        self.assertIn("the selected code imports this function", visible)
        self.assertIn("src/service.py", rendered.markdown)
        self.assertNotIn("src/helper.py", rendered.markdown)
        self.assertNotIn("helper.run", rendered.markdown)
        self.assertNotIn("json", rendered.markdown)
        self.assertEqual(disclosure_counts(rendered), (1, 1, 1, 2, 1))

    def test_interactive_prompt_target_is_preselected(self) -> None:
        output = TtyBuffer()

        rendered = review_brief(
            "no matching terms",
            source_index(),
            source_notes(),
            input_stream=TtyBuffer("y\n\n\n\ny\ny\nn\nn\nn\n"),
            output_stream=output,
            initial_selectors=("neighbor-id",),
        )

        self.assertIn("helper.run", rendered.markdown)
        self.assertIn("src/helper.py", rendered.markdown)
        self.assertIn("Other code connected to your selection", output.getvalue())

    def test_korean_review_explains_candidates_and_connected_code(self) -> None:
        output = TtyBuffer()

        review_brief(
            "retry",
            source_index(),
            source_notes(),
            input_stream=TtyBuffer("y\n1\nsrc/service.py\n\n\n\nn\nn\nn\nn\nn\n"),
            output_stream=output,
            cli_language="ko",
        )

        visible = output.getvalue()
        self.assertIn("[주의] 프롬프트에는 다음 내용이 들어가면 좋습니다:", visible)
        self.assertIn("이 프롬프트로 계속할까요? [y/N]:", visible)
        self.assertIn("코드 후보:", visible)
        self.assertIn("[1] 파일(모듈) service", visible)
        self.assertIn('파일 경로, 사용자 메모에서 "retry" 일치', visible)
        self.assertIn("관련도: 9점", visible)
        self.assertIn("함께 확인할 코드 (선택 사항):", visible)
        self.assertIn("[r1] 함수 helper.run", visible)
        self.assertIn("선택한 코드가 이 함수를 호출함", visible)
        self.assertIn("선택한 코드가 이 함수를 불러옴(import)", visible)
        self.assertIn(
            "소스코드를 포함할 함수나 클래스 번호를 선택하세요 "
            "(소스코드 없이 파일 정보만 포함하려면 Enter):",
            visible,
        )
        self.assertNotIn("연관 맥락", visible)

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
        self.assertIn("Candidates:\n", visible)
        self.assertIn("No matching code was found.", visible)
        self.assertIn("Functions and classes in `src/guided.py`:", visible)
        self.assertIn("1. class Service", visible)
        self.assertIn("2. function Service.run", visible)
        self.assertIn(
            "Select function or class numbers to include their source code "
            "(press Enter to include file details only, without source code):",
            visible,
        )
        outline = visible.split("Functions and classes in `src/guided.py`:\n", 1)[1].split(
            "Select function or class numbers", 1
        )[0]
        self.assertNotIn("module guided", outline)
        self.assertNotIn("Functions and classes in", node_id_output.getvalue())
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

        self.assertIn("[r1] class Service", output.getvalue())
        self.assertIn("the selected code contains this class", output.getvalue())
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
