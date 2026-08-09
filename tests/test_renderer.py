from __future__ import annotations

import unittest
from dataclasses import FrozenInstanceError
from typing import cast

from silobrief.python_structure import DefinitionKind
from silobrief.renderer import (
    ApprovedBoundary,
    ApprovedSymbol,
    BriefInput,
    DisclosureManifest,
    RenderError,
    render_brief,
)
from silobrief.source_review import ApprovedSourceExcerpt

SECTION_TITLES = (
    "경고와 공개 범위",
    "작업 요청",
    "승인된 프로젝트 맥락",
    "사용자 작성 메모",
    "등록된 경계",
    "승인된 소스 코드",
    "외부 AI 응답 계약",
    "Disclosure manifest",
)


def source_excerpt(**changes: object) -> ApprovedSourceExcerpt:
    values: dict[str, object] = {
        "path": "src/api.py",
        "kind": "function",
        "qualified_name": "RetryClient.send",
        "start_line": 10,
        "end_line": 12,
        "content": "def send():\n    # PUBLIC_SOURCE_CANARY\n    return '```'\n",
        "boundary_aliases": ("private-api",),
    }
    values.update(changes)
    return ApprovedSourceExcerpt(
        path=cast(str, values["path"]),
        kind=cast(DefinitionKind, values["kind"]),
        qualified_name=cast(str, values["qualified_name"]),
        start_line=cast(int, values["start_line"]),
        end_line=cast(int, values["end_line"]),
        content=cast(str, values["content"]),
        boundary_aliases=cast(tuple[str, ...], values["boundary_aliases"]),
    )


def brief_input(**changes: object) -> BriefInput:
    values: dict[str, object] = {
        "user_prompt": "재시도 동작을 수정하고 테스트해줘",
        "relative_paths": ("src/api.py",),
        "symbols": (ApprovedSymbol("function", "RetryClient.send"),),
        "public_imports": ("urllib3",),
        "human_notes": ("Python 3.10과 urllib3 2.7.0을 사용한다",),
        "boundaries": (ApprovedBoundary("private-api", "사내 전송 계층"),),
        "source_excerpts": (source_excerpt(),),
    }
    values.update(changes)
    return BriefInput(
        user_prompt=cast(str, values["user_prompt"]),
        relative_paths=cast(tuple[str, ...], values["relative_paths"]),
        symbols=cast(tuple[ApprovedSymbol, ...], values["symbols"]),
        public_imports=cast(tuple[str, ...], values["public_imports"]),
        human_notes=cast(tuple[str, ...], values["human_notes"]),
        boundaries=cast(tuple[ApprovedBoundary, ...], values["boundaries"]),
        source_excerpts=cast(tuple[ApprovedSourceExcerpt, ...], values["source_excerpts"]),
    )


class BriefRendererTests(unittest.TestCase):
    def test_renders_v3_single_brief_and_manifest_deterministically(self) -> None:
        first_excerpt = source_excerpt()
        second_excerpt = source_excerpt(
            path="src/client.py",
            qualified_name="RetryClient",
            kind="class",
            start_line=2,
            end_line=3,
            content="class RetryClient:\n    pass\n",
            boundary_aliases=(),
        )
        source = brief_input(
            user_prompt="재시도 동작 확인\n## 삽입 제목",
            relative_paths=("src/z.py", "src/a.py", "src/z.py"),
            symbols=(
                ApprovedSymbol("function", "send"),
                ApprovedSymbol("class", "RetryClient"),
                ApprovedSymbol("function", "send"),
            ),
            public_imports=("urllib3", "Python", "urllib3"),
            human_notes=("첫 번째 메모", "두 번째 메모\n## 메모 제목"),
            boundaries=(
                ApprovedBoundary("transport", "전송 구현"),
                ApprovedBoundary("account", "계정 연동"),
                ApprovedBoundary("transport", "전송 구현"),
            ),
            source_excerpts=(first_excerpt, second_excerpt),
        )

        rendered = render_brief(source)
        reordered = render_brief(
            brief_input(
                user_prompt=source.user_prompt,
                relative_paths=tuple(reversed(source.relative_paths)),
                symbols=tuple(reversed(source.symbols)),
                public_imports=tuple(reversed(source.public_imports)),
                human_notes=source.human_notes,
                boundaries=tuple(reversed(source.boundaries)),
                source_excerpts=tuple(reversed(source.source_excerpts)),
            )
        )

        headings: list[str] = []
        in_fence = False
        for line in rendered.markdown.splitlines():
            if line.startswith("```"):
                in_fence = not in_fence
            elif not in_fence and line.startswith("## "):
                headings.append(line.removeprefix("## "))
        self.assertEqual(rendered, reordered)
        self.assertEqual(tuple(headings), SECTION_TITLES)
        self.assertTrue(rendered.markdown.endswith("\n"))
        self.assertNotIn("\r", rendered.markdown)
        self.assertIn("PUBLIC_SOURCE_CANARY", rendered.markdown)
        self.assertIn("````python", rendered.markdown)
        self.assertNotIn("조사 질문", rendered.markdown)
        self.assertNotIn("추천 검색어", rendered.markdown)
        self.assertNotIn("외부 AI에 전달할 요청", rendered.markdown)
        self.assertNotIn("수동 확인 체크리스트", rendered.markdown)
        self.assertTrue(
            rendered.markdown.startswith("> 이 문서의 승인된 프로젝트 맥락과 소스 코드만 사용하여")
        )
        self.assertIn("공개 import", rendered.markdown)
        self.assertIn("## 바로 적용할 변경", rendered.markdown)
        self.assertIn("## 패치", rendered.markdown)
        self.assertIn("`diff` 코드 블록", rendered.markdown)
        for marker in ("`-`", "`+`"):
            self.assertIn(marker, rendered.markdown)
        for optional in ("unified diff", "--- a/경로", "+++ b/경로", "/dev/null"):
            self.assertNotIn(optional, rendered.markdown)
        self.assertIn("`git apply` 가능성을 주장하지 마세요", rendered.markdown)
        self.assertNotIn("패치 또는 교체 코드", rendered.markdown)
        self.assertNotIn("TASK_ANSWER_CANARY", rendered.markdown)
        self.assertEqual(
            rendered.disclosure,
            DisclosureManifest(
                schema_version=3,
                user_prompt="included",
                relative_paths=2,
                symbol_names=2,
                public_imports=2,
                human_notes=2,
                human_notes_content="user-supplied-unclassified",
                boundary_aliases=2,
                source_delivery="embedded",
                source_excerpts=2,
                source_lines=5,
                source_utf8_bytes=sum(
                    len(item.content.encode("utf-8")) for item in (first_excerpt, second_excerpt)
                ),
                source_content_mode="verbatim",
                boundary_aliases_exposed_in_source=1,
                renderer_added_absolute_paths=0,
                renderer_added_git_remotes=0,
            ),
        )

    def test_renders_main_only_when_no_source_is_approved(self) -> None:
        rendered = render_brief(brief_input(source_excerpts=()))

        self.assertNotIn("## 승인된 소스 코드", rendered.markdown)
        self.assertTrue(rendered.markdown.startswith("> 이 문서에 공개된 프로젝트 맥락만 사용하여"))
        self.assertEqual(rendered.disclosure.source_delivery, "none")
        self.assertEqual(rendered.disclosure.source_excerpts, 0)
        self.assertEqual(rendered.disclosure.source_content_mode, "none")

    def test_omits_empty_optional_context_sections(self) -> None:
        rendered = render_brief(
            brief_input(
                human_notes=(),
                boundaries=(),
                source_excerpts=(),
            )
        )

        for title in ("사용자 작성 메모", "등록된 경계", "승인된 소스 코드"):
            self.assertNotIn(f"## {title}", rendered.markdown)

    def test_rejects_objects_outside_the_renderer_whitelist(self) -> None:
        unsafe: object = {"user_prompt": "task", "source_body": "SOURCE_BODY_CANARY"}

        with self.assertRaisesRegex(RenderError, "whitelist"):
            render_brief(cast(BriefInput, unsafe))

    def test_input_models_are_immutable_and_slotted(self) -> None:
        source = brief_input()

        self.assertFalse(hasattr(source, "__dict__"))
        with self.assertRaises(FrozenInstanceError):
            source.user_prompt = "changed"  # type: ignore[misc]

    def test_rejects_invalid_fields_and_source_spans(self) -> None:
        invalid_inputs = (
            (brief_input(user_prompt="  \n"), "user prompt"),
            (brief_input(relative_paths=("../secret.py",)), "relative path"),
            (brief_input(relative_paths=("C:/secret.py",)), "relative path"),
            (brief_input(relative_paths=("src\\secret.py",)), "relative path"),
            (brief_input(symbols=(ApprovedSymbol("function", "  "),)), "symbol name"),
            (brief_input(public_imports=("",)), "public import"),
            (brief_input(human_notes=("\n",)), "human note"),
            (
                brief_input(boundaries=(ApprovedBoundary("", "public description"),)),
                "boundary alias",
            ),
            (brief_input(source_excerpts=(source_excerpt(path="../secret.py"),)), "relative path"),
            (brief_input(source_excerpts=(source_excerpt(start_line=0),)), "source span"),
            (brief_input(source_excerpts=(source_excerpt(end_line=11),)), "source span"),
            (
                brief_input(
                    source_excerpts=(source_excerpt(content="def send():\r\n    pass\r\n"),)
                ),
                "source content",
            ),
            (
                brief_input(source_excerpts=(source_excerpt(boundary_aliases=("bad\nalias",)),)),
                "boundary alias",
            ),
        )

        for source, message in invalid_inputs:
            with self.subTest(message=message):
                with self.assertRaisesRegex(RenderError, message):
                    render_brief(source)


if __name__ == "__main__":
    unittest.main()
