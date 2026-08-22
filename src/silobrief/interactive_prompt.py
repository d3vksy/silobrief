from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import CompleteEvent, Completer, Completion
from prompt_toolkit.document import Document
from prompt_toolkit.input.base import Input
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.key_binding.key_processor import KeyPressEvent
from prompt_toolkit.output.base import Output
from prompt_toolkit.validation import Validator

from silobrief.index import IndexData
from silobrief.language import Language, localized
from silobrief.terminal import escape_terminal_line


class InteractivePromptError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class PromptComposition:
    prompt: str
    selectors: tuple[str, ...]


class _SubstringCompleter(Completer):
    def __init__(self, choices: Iterable[str]) -> None:
        self._choices = tuple(sorted(set(choices), key=lambda value: (value.casefold(), value)))

    def get_completions(self, document: Document, complete_event: object) -> Iterable[Completion]:
        del complete_event
        entered = document.text_before_cursor
        query = entered.casefold()
        for choice in self._choices:
            if query in choice.casefold():
                yield Completion(choice, start_position=-len(entered), display=choice)


_COMPLETION_BINDINGS = KeyBindings()


@_COMPLETION_BINDINGS.add("tab")
def _accept_completion(event: KeyPressEvent) -> None:
    buffer = event.current_buffer
    state = buffer.complete_state
    if state is not None and state.current_completion is not None:
        buffer.apply_completion(state.current_completion)
    elif state is not None and state.completions:
        buffer.apply_completion(state.completions[0])
    elif buffer.completer is not None:
        completions = tuple(
            buffer.completer.get_completions(
                buffer.document,
                CompleteEvent(completion_requested=True),
            )
        )
        if completions:
            buffer.apply_completion(completions[0])


def compose_brief_prompt(
    index: IndexData,
    file_paths: tuple[str, ...],
    *,
    language: Language,
    prompt_input: Input | None = None,
    prompt_output: Output | None = None,
) -> PromptComposition:
    safe_paths = _safe_values(file_paths)
    functions = _function_choices(index, safe_paths)
    session: PromptSession[str] = PromptSession(input=prompt_input, output=prompt_output)

    request = session.prompt(
        localized(language, "Task: ", "작업: "),
        validator=_required_validator(language),
        validate_while_typing=False,
    ).strip()
    selected_files: list[str] = []
    selected_functions: list[tuple[str, str, str]] = []

    while True:
        command = session.prompt(
            localized(
                language,
                "Add context (/file, /func, press Enter to continue): ",
                "정보 추가 (/file, /func, 계속하려면 Enter): ",
            ),
            completer=_SubstringCompleter(("/file", "/func")),
            complete_while_typing=True,
            validator=_command_validator(language),
            validate_while_typing=False,
            reserve_space_for_menu=3,
            key_bindings=_COMPLETION_BINDINGS,
        ).strip()
        if not command:
            break
        if command == "/file":
            path = _choose(
                session,
                localized(language, "File: ", "파일: "),
                safe_paths,
                language,
            )
            if path not in selected_files:
                selected_files.append(path)
            continue

        function_paths = tuple(functions)
        if not function_paths:
            raise InteractivePromptError(
                localized(
                    language,
                    "no indexed functions or methods are available",
                    "선택할 수 있는 함수나 메서드가 없습니다",
                )
            )
        path = _choose(
            session,
            localized(language, "Python file: ", "Python 파일: "),
            function_paths,
            language,
        )
        qualified_name = _choose(
            session,
            localized(language, "Function or method: ", "함수 또는 메서드: "),
            tuple(functions[path]),
            language,
        )
        selected = (path, qualified_name, functions[path][qualified_name])
        if selected not in selected_functions:
            selected_functions.append(selected)

    selectors = _selectors(index, selected_files, selected_functions)
    return PromptComposition(
        prompt=_append_targets(request, selected_files, selected_functions, language),
        selectors=selectors,
    )


def _choose(
    session: PromptSession[str],
    label: str,
    choices: tuple[str, ...],
    language: Language,
) -> str:
    if not choices:
        raise InteractivePromptError(
            localized(language, "no selectable items are available", "선택할 항목이 없습니다")
        )
    return session.prompt(
        label,
        completer=_SubstringCompleter(choices),
        complete_while_typing=True,
        validator=_choice_validator(frozenset(choices), language),
        validate_while_typing=False,
        reserve_space_for_menu=8,
        key_bindings=_COMPLETION_BINDINGS,
    )


def _safe_values(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(
        sorted(
            {value for value in values if value and escape_terminal_line(value) == value},
            key=lambda value: (value.casefold(), value),
        )
    )


def _function_choices(index: IndexData, safe_paths: tuple[str, ...]) -> dict[str, dict[str, str]]:
    allowed_paths = frozenset(safe_paths)
    functions: dict[str, dict[str, str]] = {}
    for node in sorted(
        index.nodes,
        key=lambda value: (value.path.casefold(), value.qualified_name.casefold(), value.id),
    ):
        if (
            node.kind != "function"
            or node.path not in allowed_paths
            or escape_terminal_line(node.qualified_name) != node.qualified_name
        ):
            continue
        functions.setdefault(node.path, {})[node.qualified_name] = node.id
    return functions


def _selectors(
    index: IndexData,
    selected_files: list[str],
    selected_functions: list[tuple[str, str, str]],
) -> tuple[str, ...]:
    indexed_paths = {node.path for node in index.nodes if node.kind == "module"}
    values = [path for path in selected_files if path in indexed_paths]
    values.extend(node_id for _path, _qualified_name, node_id in selected_functions)
    return tuple(dict.fromkeys(values))


def _append_targets(
    request: str,
    selected_files: list[str],
    selected_functions: list[tuple[str, str, str]],
    language: Language,
) -> str:
    if not selected_files and not selected_functions:
        return request
    lines = ["", localized(language, "Selected project context:", "선택한 프로젝트 정보:")]
    file_label = localized(language, "File", "파일")
    function_label = localized(language, "Function or method", "함수 또는 메서드")
    lines.extend(
        f"- {file_label}: {json.dumps(path, ensure_ascii=False)}" for path in selected_files
    )
    lines.extend(
        f"- {function_label}: {json.dumps(f'{path}::{qualified_name}', ensure_ascii=False)}"
        for path, qualified_name, _node_id in selected_functions
    )
    return "\n".join((request, *lines))


def _required_validator(language: Language) -> Validator:
    return Validator.from_callable(
        lambda value: bool(value.strip()),
        error_message=localized(
            language,
            "request must not be empty",
            "요청은 비어 있을 수 없습니다",
        ),
        move_cursor_to_end=True,
    )


def _command_validator(language: Language) -> Validator:
    return Validator.from_callable(
        lambda value: not value.strip() or value.strip() in {"/file", "/func"},
        error_message=localized(
            language,
            "enter /file or /func, or press Enter to continue",
            "/file, /func를 입력하거나 Enter를 누르세요",
        ),
        move_cursor_to_end=True,
    )


def _choice_validator(choices: frozenset[str], language: Language) -> Validator:
    return Validator.from_callable(
        lambda value: value in choices,
        error_message=localized(
            language,
            "select an item from the completion menu",
            "자동완성 메뉴에서 항목을 선택하세요",
        ),
        move_cursor_to_end=True,
    )
