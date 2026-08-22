from __future__ import annotations

import unittest

from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput

from silobrief.index import IndexData, IndexNode, NodeKind, NodeTokens
from silobrief.interactive_prompt import (
    InteractivePromptError,
    _safe_values,
    compose_brief_prompt,
)

TOKENS = NodeTokens(path=(), symbol=(), imports=(), comments=(), docstrings=())


def node(
    node_id: str,
    path: str,
    kind: NodeKind,
    name: str,
    qualified_name: str | None = None,
) -> IndexNode:
    return IndexNode(
        id=node_id,
        kind=kind,
        name=name,
        qualified_name=qualified_name or name,
        path=path,
        tokens=TOKENS,
    )


def source_index() -> IndexData:
    return IndexData(
        config_digest="a" * 64,
        edges=(),
        index_version=1,
        nodes=(
            node("app-module", "app.py", "module", "app"),
            node("login-node", "app.py", "function", "login"),
            node("method-node", "app.py", "function", "issue", "TokenService.issue"),
            node("helper-module", "src/helper.py", "module", "helper"),
            node("helper-node", "src/helper.py", "function", "load"),
        ),
        source_digest="b" * 64,
        stale=False,
    )


class InteractivePromptTests(unittest.TestCase):
    def test_tab_completes_file_and_function_targets(self) -> None:
        with create_pipe_input() as prompt_input:
            prompt_input.send_text(
                "로그인 성공 시 JWT를 반환해줘\r/fi\t\rreq\t\r/fu\t\rapp\t\rlog\t\r\r"
            )
            result = compose_brief_prompt(
                source_index(),
                ("app.py", "requirements.txt", "src/helper.py"),
                language="ko",
                prompt_input=prompt_input,
                prompt_output=DummyOutput(),
            )

        self.assertIn('파일: "requirements.txt"', result.prompt)
        self.assertIn('함수 또는 메서드: "app.py::login"', result.prompt)
        self.assertEqual(result.selectors, ("login-node",))

    def test_python_file_target_is_preselected_once(self) -> None:
        with create_pipe_input() as prompt_input:
            prompt_input.send_text("Fix helper\r/file\rsrc/helper.py\r/file\rsrc/helper.py\r\r")
            result = compose_brief_prompt(
                source_index(),
                ("app.py", "requirements.txt", "src/helper.py"),
                language="en",
                prompt_input=prompt_input,
                prompt_output=DummyOutput(),
            )

        self.assertEqual(result.prompt.count('File: "src/helper.py"'), 1)
        self.assertIn("Selected project context:", result.prompt)
        self.assertEqual(result.selectors, ("src/helper.py",))

    def test_control_character_paths_are_not_selectable(self) -> None:
        self.assertEqual(_safe_values(("app.py", "unsafe\x1b[2J.py")), ("app.py",))

    def test_func_reports_an_empty_function_index(self) -> None:
        index = IndexData(
            config_digest="a" * 64,
            edges=(),
            index_version=1,
            nodes=(node("module", "app.py", "module", "app"),),
            source_digest="b" * 64,
            stale=False,
        )
        with create_pipe_input() as prompt_input:
            prompt_input.send_text("Fix app\r/func\r")
            with self.assertRaisesRegex(InteractivePromptError, "no indexed functions or methods"):
                compose_brief_prompt(
                    index,
                    ("app.py",),
                    language="en",
                    prompt_input=prompt_input,
                    prompt_output=DummyOutput(),
                )


if __name__ == "__main__":
    unittest.main()
