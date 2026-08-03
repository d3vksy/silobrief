from __future__ import annotations

import unittest
from dataclasses import FrozenInstanceError
from typing import cast

from silobrief.renderer import (
    ApprovedBoundary,
    ApprovedSymbol,
    BriefInput,
    DisclosureManifest,
    RenderError,
    render_brief,
)

SECTION_TITLES = (
    "경고와 용도",
    "원래 작업 요청",
    "선택한 프로젝트 맥락",
    "사용자 작성 메모",
    "숨긴 경계",
    "조사 질문",
    "추천 검색어",
    "외부 AI에 복사할 프롬프트",
    "Disclosure manifest",
    "수동 확인 체크리스트",
)


def brief_input(**changes: object) -> BriefInput:
    values: dict[str, object] = {
        "user_prompt": "공식 재시도 동작을 확인해줘",
        "relative_paths": ("src/api.py",),
        "symbols": (ApprovedSymbol("function", "RetryClient.send"),),
        "public_dependencies": ("urllib3",),
        "human_notes": ("Python 3.10을 지원해야 한다",),
        "boundaries": (ApprovedBoundary("private-api", "사내 전송 계층"),),
    }
    values.update(changes)
    return BriefInput(
        user_prompt=cast(str, values["user_prompt"]),
        relative_paths=cast(tuple[str, ...], values["relative_paths"]),
        symbols=cast(tuple[ApprovedSymbol, ...], values["symbols"]),
        public_dependencies=cast(tuple[str, ...], values["public_dependencies"]),
        human_notes=cast(tuple[str, ...], values["human_notes"]),
        boundaries=cast(tuple[ApprovedBoundary, ...], values["boundaries"]),
    )


class BriefRendererTests(unittest.TestCase):
    def test_renders_exact_sections_manifest_and_only_approved_values(self) -> None:
        source = BriefInput(
            user_prompt="재시도 동작 확인\n## 삽입 제목",
            relative_paths=("src/z.py", "src/a.py", "src/z.py"),
            symbols=(
                ApprovedSymbol("function", "send"),
                ApprovedSymbol("class", "RetryClient"),
                ApprovedSymbol("function", "send"),
            ),
            public_dependencies=("urllib3", "Python", "urllib3"),
            human_notes=("첫 번째 메모", "두 번째 메모\n## 메모 제목"),
            boundaries=(
                ApprovedBoundary("transport", "전송 구현"),
                ApprovedBoundary("account", "계정 연동"),
                ApprovedBoundary("transport", "전송 구현"),
            ),
        )

        rendered = render_brief(source)
        reordered = render_brief(
            BriefInput(
                user_prompt=source.user_prompt,
                relative_paths=tuple(reversed(source.relative_paths)),
                symbols=tuple(reversed(source.symbols)),
                public_dependencies=tuple(reversed(source.public_dependencies)),
                human_notes=source.human_notes,
                boundaries=tuple(reversed(source.boundaries)),
            )
        )

        headings = tuple(
            line.removeprefix("## ")
            for line in rendered.markdown.splitlines()
            if line.startswith("## ")
        )
        self.assertEqual(rendered, reordered)
        self.assertEqual(headings, SECTION_TITLES)
        self.assertTrue(rendered.markdown.endswith("\n"))
        self.assertNotIn("\r", rendered.markdown)
        for approved in (
            "재시도 동작 확인",
            "src/a.py",
            "src/z.py",
            "RetryClient",
            "send",
            "Python",
            "urllib3",
            "첫 번째 메모",
            "두 번째 메모",
            "account",
            "계정 연동",
            "transport",
            "전송 구현",
        ):
            self.assertIn(approved, rendered.markdown)
        self.assertLess(
            rendered.markdown.index("첫 번째 메모"), rendered.markdown.index("두 번째 메모")
        )
        self.assertIn("official documentation", rendered.markdown)
        self.assertIn("AI를 호출하거나 전송하지 않습니다", rendered.markdown)
        self.assertIn("사람이 전체 내용을 확인해야 합니다", rendered.markdown)
        self.assertEqual(
            rendered.disclosure,
            DisclosureManifest(
                user_prompt="included",
                relative_paths=2,
                symbol_names=2,
                public_dependencies=2,
                human_notes=2,
                boundary_aliases=2,
                source_bodies=0,
                comments=0,
                docstrings=0,
                string_literals=0,
                absolute_paths=0,
                git_remotes=0,
                ignored_real_names=0,
            ),
        )
        self.assertIn("  ignored_real_names: 0", rendered.markdown)

    def test_renders_empty_approved_context_without_inventing_values(self) -> None:
        rendered = render_brief(
            BriefInput(
                user_prompt="공식 문서를 확인해줘",
                relative_paths=(),
                symbols=(),
                public_dependencies=(),
                human_notes=(),
                boundaries=(),
            )
        )

        self.assertEqual(rendered.markdown.count("- 없음"), 5)
        self.assertEqual(rendered.disclosure.relative_paths, 0)
        self.assertEqual(rendered.disclosure.symbol_names, 0)
        self.assertEqual(rendered.disclosure.public_dependencies, 0)
        self.assertEqual(rendered.disclosure.human_notes, 0)
        self.assertEqual(rendered.disclosure.boundary_aliases, 0)

    def test_rejects_objects_outside_the_renderer_whitelist(self) -> None:
        unsafe: object = {
            "user_prompt": "task",
            "source_body": "SOURCE_BODY_CANARY",
        }

        with self.assertRaisesRegex(RenderError, "whitelist"):
            render_brief(cast(BriefInput, unsafe))

    def test_input_models_are_immutable_and_slotted(self) -> None:
        source = brief_input()

        self.assertFalse(hasattr(source, "__dict__"))
        with self.assertRaises(FrozenInstanceError):
            source.user_prompt = "changed"  # type: ignore[misc]

    def test_rejects_empty_fields_and_unsafe_relative_paths(self) -> None:
        invalid_inputs = (
            (brief_input(user_prompt="  \n"), "user prompt"),
            (brief_input(relative_paths=("",)), "relative path"),
            (brief_input(relative_paths=("../secret.py",)), "relative path"),
            (brief_input(relative_paths=("C:/secret.py",)), "relative path"),
            (brief_input(relative_paths=("src\\secret.py",)), "relative path"),
            (brief_input(symbols=(ApprovedSymbol("function", "  "),)), "symbol name"),
            (brief_input(public_dependencies=("",)), "public dependency"),
            (brief_input(human_notes=("\n",)), "human note"),
            (
                brief_input(boundaries=(ApprovedBoundary("", "public description"),)),
                "boundary alias",
            ),
            (
                brief_input(boundaries=(ApprovedBoundary("private", "  "),)),
                "boundary description",
            ),
        )

        for source, message in invalid_inputs:
            with self.subTest(message=message):
                with self.assertRaisesRegex(RenderError, message):
                    render_brief(source)


if __name__ == "__main__":
    unittest.main()
