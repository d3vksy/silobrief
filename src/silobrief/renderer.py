from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath, PureWindowsPath
from typing import Literal

from silobrief.index import NodeKind
from silobrief.language import Language
from silobrief.source_excerpts import MAX_SOURCE_LINES, MAX_SOURCE_UTF8_BYTES
from silobrief.source_review import ApprovedSourceExcerpt

_KIND_ORDER = {"module": 0, "class": 1, "function": 2}
_WARNING_KO = (
    "승인된 소스의 민감정보를 자동으로 탐지하거나 반출 안전성을 보장하지 않습니다. "
    "전달 전에 모든 출력 파일을 직접 확인하세요."
)
_WARNING_EN = (
    "siloBrief does not automatically detect sensitive information in approved source or "
    "guarantee that an export is safe to share. Review every output file before sharing it."
)


class RenderError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ApprovedSymbol:
    kind: NodeKind
    name: str


@dataclass(frozen=True, slots=True)
class ApprovedBoundary:
    alias: str
    description: str


@dataclass(frozen=True, slots=True)
class BriefInput:
    user_prompt: str
    relative_paths: tuple[str, ...]
    symbols: tuple[ApprovedSymbol, ...]
    public_imports: tuple[str, ...]
    human_notes: tuple[str, ...]
    boundaries: tuple[ApprovedBoundary, ...]
    source_excerpts: tuple[ApprovedSourceExcerpt, ...]


@dataclass(frozen=True, slots=True)
class DisclosureManifest:
    schema_version: Literal[3]
    user_prompt: Literal["included"]
    relative_paths: int
    symbol_names: int
    public_imports: int
    human_notes: int
    human_notes_content: Literal["user-supplied-unclassified"]
    boundary_aliases: int
    source_delivery: Literal["embedded", "none"]
    source_excerpts: int
    source_lines: int
    source_utf8_bytes: int
    source_content_mode: Literal["verbatim", "none"]
    boundary_aliases_exposed_in_source: int
    renderer_added_absolute_paths: Literal[0]
    renderer_added_git_remotes: Literal[0]


@dataclass(frozen=True, slots=True)
class RenderedBrief:
    markdown: str
    disclosure: DisclosureManifest


def render_brief(source: BriefInput, *, language: Language = "en") -> RenderedBrief:
    approved = _prepare(source)
    disclosure = _disclosure(approved)
    if language == "ko":
        return _render_korean(approved, disclosure)
    return _render_english(approved, disclosure)


def _render_korean(source: BriefInput, disclosure: DisclosureManifest) -> RenderedBrief:
    sections = [
        _execution_instruction(bool(source.source_excerpts), language="ko"),
        _section("경고와 공개 범위", _WARNING_KO),
        _section("작업 요청", _quote(source.user_prompt)),
        _section("승인된 프로젝트 맥락", _project_context(source, language="ko")),
    ]
    if source.human_notes:
        sections.append(
            _section("사용자 작성 메모", _quoted_list(source.human_notes, language="ko"))
        )
    if source.boundaries:
        sections.append(_section("등록된 경계", _boundary_list(source.boundaries, language="ko")))
    source_markdown = _source_markdown(source.source_excerpts, language="ko")
    if source_markdown is not None:
        sections.append(_section("승인된 소스 코드", source_markdown))
    sections.extend(
        (
            _section("외부 AI 응답 계약", _response_contract()),
            _section("공개 내역", _manifest_yaml(disclosure)),
        )
    )
    return RenderedBrief(
        markdown="\n\n".join(sections) + "\n",
        disclosure=disclosure,
    )


def _render_english(source: BriefInput, disclosure: DisclosureManifest) -> RenderedBrief:
    sections = [
        _execution_instruction(bool(source.source_excerpts), language="en"),
        _section("Warning and disclosure scope", _WARNING_EN),
        _section("Task request", _quote(source.user_prompt)),
        _section("Approved project context", _project_context(source, language="en")),
    ]
    if source.human_notes:
        sections.append(
            _section("User-authored notes", _quoted_list(source.human_notes, language="en"))
        )
    if source.boundaries:
        sections.append(
            _section("Registered boundaries", _boundary_list(source.boundaries, language="en"))
        )
    source_markdown = _source_markdown(source.source_excerpts, language="en")
    if source_markdown is not None:
        sections.append(_section("Approved source code", source_markdown))
    sections.extend(
        (
            _section("External AI response contract", _response_contract_english()),
            _section("Disclosure manifest", _manifest_yaml(disclosure)),
        )
    )
    return RenderedBrief(markdown="\n\n".join(sections) + "\n", disclosure=disclosure)


def _prepare(source: BriefInput) -> BriefInput:
    if type(source) is not BriefInput:
        raise RenderError("renderer accepts only the BriefInput whitelist")
    prompt = _text(source.user_prompt, "user prompt")
    paths = tuple(sorted({_relative_path(value) for value in source.relative_paths}))
    symbols = _symbols(source.symbols)
    public_imports = tuple(
        sorted({_single_line(value, "public import") for value in source.public_imports})
    )
    notes = tuple(_text(value, "human note") for value in source.human_notes)
    boundaries = _boundaries(source.boundaries)
    excerpts = _source_excerpts(source.source_excerpts)
    return BriefInput(
        prompt,
        paths,
        symbols,
        public_imports,
        notes,
        boundaries,
        excerpts,
    )


def _symbols(values: tuple[ApprovedSymbol, ...]) -> tuple[ApprovedSymbol, ...]:
    result: set[ApprovedSymbol] = set()
    for value in values:
        if type(value) is not ApprovedSymbol or value.kind not in _KIND_ORDER:
            raise RenderError("symbol kind is invalid")
        result.add(ApprovedSymbol(value.kind, _single_line(value.name, "symbol name")))
    return tuple(sorted(result, key=lambda item: (_KIND_ORDER[item.kind], item.name)))


def _boundaries(values: tuple[ApprovedBoundary, ...]) -> tuple[ApprovedBoundary, ...]:
    result: dict[str, ApprovedBoundary] = {}
    for value in values:
        if type(value) is not ApprovedBoundary:
            raise RenderError("boundary value is invalid")
        boundary = ApprovedBoundary(
            _single_line(value.alias, "boundary alias"),
            _text(value.description, "boundary description"),
        )
        existing = result.get(boundary.alias)
        if existing is not None and existing != boundary:
            raise RenderError("boundary alias has conflicting descriptions")
        result[boundary.alias] = boundary
    return tuple(sorted(result.values(), key=lambda item: (item.alias, item.description)))


def _source_excerpts(
    values: tuple[ApprovedSourceExcerpt, ...],
) -> tuple[ApprovedSourceExcerpt, ...]:
    result: dict[tuple[str, int, int, str, str], ApprovedSourceExcerpt] = {}
    for value in values:
        if type(value) is not ApprovedSourceExcerpt or value.kind not in {"class", "function"}:
            raise RenderError("source excerpt value is invalid")
        path = _relative_path(value.path)
        name = _single_line(value.qualified_name, "source qualified name")
        if value.start_line < 1 or value.end_line < value.start_line:
            raise RenderError("source span is invalid")
        content = _source_content(value.content)
        line_count = content.count("\n") + (0 if content.endswith("\n") else 1)
        if line_count != value.end_line - value.start_line + 1:
            raise RenderError("source span does not match source content")
        aliases = tuple(
            sorted({_single_line(alias, "boundary alias") for alias in value.boundary_aliases})
        )
        excerpt = ApprovedSourceExcerpt(
            path,
            value.kind,
            name,
            value.start_line,
            value.end_line,
            content,
            aliases,
        )
        key = (path, value.start_line, value.end_line, value.kind, name)
        existing = result.get(key)
        if existing is not None and existing != excerpt:
            raise RenderError("source excerpt has conflicting content")
        result[key] = excerpt

    ordered = tuple(
        sorted(
            result.values(),
            key=lambda item: (
                item.path,
                item.start_line,
                item.end_line,
                item.qualified_name,
            ),
        )
    )
    _validate_source_totals(ordered)
    _validate_source_overlaps(ordered)
    return ordered


def _source_content(value: object) -> str:
    if not isinstance(value, str) or not value or "\r" in value:
        raise RenderError("source content must be non-empty LF text")
    try:
        value.encode("utf-8")
    except UnicodeError as error:
        raise RenderError("source content must be valid UTF-8 text") from error
    return value


def _validate_source_totals(values: tuple[ApprovedSourceExcerpt, ...]) -> None:
    lines = sum(value.line_count for value in values)
    utf8_bytes = sum(value.utf8_bytes for value in values)
    if lines > MAX_SOURCE_LINES or utf8_bytes > MAX_SOURCE_UTF8_BYTES:
        raise RenderError("source excerpts exceed the disclosure limit")


def _validate_source_overlaps(values: tuple[ApprovedSourceExcerpt, ...]) -> None:
    previous: ApprovedSourceExcerpt | None = None
    for value in values:
        if (
            previous is not None
            and value.path == previous.path
            and value.start_line <= previous.end_line
        ):
            raise RenderError("source excerpts overlap")
        previous = value


def _text(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise RenderError(f"{label} must be text")
    normalized = value.replace("\r\n", "\n").replace("\r", "\n")
    if not normalized.strip():
        raise RenderError(f"{label} must not be empty")
    return normalized


def _single_line(value: object, label: str) -> str:
    text = _text(value, label)
    if "\n" in text:
        raise RenderError(f"{label} must be a single line")
    return text


def _relative_path(value: object) -> str:
    path = _single_line(value, "relative path")
    posix = PurePosixPath(path)
    windows = PureWindowsPath(path)
    if (
        "\\" in path
        or posix.is_absolute()
        or windows.drive
        or windows.root
        or ".." in posix.parts
        or posix.as_posix() != path
    ):
        raise RenderError("relative path must be normalized and stay inside the project")
    return path


def _disclosure(source: BriefInput) -> DisclosureManifest:
    aliases = {alias for excerpt in source.source_excerpts for alias in excerpt.boundary_aliases}
    return DisclosureManifest(
        schema_version=3,
        user_prompt="included",
        relative_paths=len(source.relative_paths),
        symbol_names=len(source.symbols),
        public_imports=len(source.public_imports),
        human_notes=len(source.human_notes),
        human_notes_content="user-supplied-unclassified",
        boundary_aliases=len(source.boundaries),
        source_delivery="embedded" if source.source_excerpts else "none",
        source_excerpts=len(source.source_excerpts),
        source_lines=sum(value.line_count for value in source.source_excerpts),
        source_utf8_bytes=sum(value.utf8_bytes for value in source.source_excerpts),
        source_content_mode="verbatim" if source.source_excerpts else "none",
        boundary_aliases_exposed_in_source=len(aliases),
        renderer_added_absolute_paths=0,
        renderer_added_git_remotes=0,
    )


def _section(title: str, body: str) -> str:
    return f"## {title}\n\n{body}"


def _execution_instruction(has_source: bool, *, language: Language) -> str:
    if language == "en":
        scope = (
            "the approved project context and source code in this document"
            if has_source
            else "the project context disclosed in this document"
        )
        return (
            f"> Use only {scope} to complete the task below. Provide applicable changes and tests."
        )
    scope = (
        "이 문서의 승인된 프로젝트 맥락과 소스 코드"
        if has_source
        else "이 문서에 공개된 프로젝트 맥락"
    )
    return (
        f"> {scope}만 사용하여 아래 작업을 수행하고, 적용 가능한 변경 코드와 테스트를 제시하세요."
    )


def _quote(value: str) -> str:
    return "\n".join(">" if not line else f"> {line}" for line in value.split("\n"))


def _quoted_list(values: tuple[str, ...], *, language: Language) -> str:
    if not values:
        return "- 없음" if language == "ko" else "- none"
    lines: list[str] = []
    for value in values:
        lines.append("- 승인 항목:" if language == "ko" else "- approved item:")
        lines.extend(f"  {line}" for line in _quote(value).splitlines())
    return "\n".join(lines)


def _project_context(source: BriefInput, *, language: Language) -> str:
    if language == "en":
        symbols = tuple(f"{item.kind}: {item.name}" for item in source.symbols)
        return "\n\n".join(
            (
                f"### Relative paths\n\n{_quoted_list(source.relative_paths, language=language)}",
                f"### Symbols\n\n{_quoted_list(symbols, language=language)}",
                f"### Public imports\n\n{_quoted_list(source.public_imports, language=language)}",
            )
        )
    kind_labels = {"module": "파일(모듈)", "class": "클래스", "function": "함수"}
    symbols = tuple(f"{kind_labels[item.kind]}: {item.name}" for item in source.symbols)
    return "\n\n".join(
        (
            f"### 상대 경로\n\n{_quoted_list(source.relative_paths, language=language)}",
            f"### 심볼\n\n{_quoted_list(symbols, language=language)}",
            f"### 공개 import\n\n{_quoted_list(source.public_imports, language=language)}",
        )
    )


def _boundary_list(values: tuple[ApprovedBoundary, ...], *, language: Language) -> str:
    if not values:
        return "- 없음" if language == "ko" else "- none"
    lines: list[str] = []
    for value in values:
        labels = (
            ("- 경계 별칭:", "  공개 설명:")
            if language == "ko"
            else (
                "- boundary alias:",
                "  public description:",
            )
        )
        lines.extend((labels[0], f"  {_quote(value.alias)}", labels[1]))
        lines.extend(f"  {line}" for line in _quote(value.description).splitlines())
    return "\n".join(lines)


def _response_contract() -> str:
    return "\n".join(
        (
            "다음 네 제목을 순서대로 사용하고, 별도 서론은 쓰지 마세요.",
            "",
            "```text",
            "## 바로 적용할 변경",
            "## 패치",
            "## 테스트",
            "## 확인 필요",
            "```",
            "",
            "- `바로 적용할 변경`에 대상 파일과 변경 목적을 먼저 적으세요.",
            "- `패치`에는 공개된 코드와 맥락만 근거로 한 `diff` 코드 블록을 넣으세요.",
            "- 수정 작업은 변경 전 줄을 `-`, 변경 후 줄을 `+`로 표시하세요. 파일 header, "
            "hunk header와 정확한 줄 번호는 선택 사항이며 `git apply` 가능성을 주장하지 마세요.",
            "- 전체 교체용 일반 코드 블록으로 대신하지 말고, 숨긴 구현을 추측하지 마세요.",
            "- 집중된 테스트를 제시하되, 실행하지 않았다면 통과했다고 표현하지 마세요.",
            "- `확인 필요`는 최대 2개로 제한하고, 외부 API 주장은 가능한 경우 버전이 "
            "고정된 공식 문서 URL로 뒷받침하세요. 확인할 내용이 없으면 `없음`이라고 적으세요.",
            "- 별도 요구가 없으면 비어 있지 않은 줄 80개 이내로 답하세요.",
        )
    )


def _response_contract_english() -> str:
    return "\n".join(
        (
            "Use the following four headings in order. Do not add a separate introduction.",
            "",
            "```text",
            "## Change to apply",
            "## Patch",
            "## Tests",
            "## Needs confirmation",
            "```",
            "",
            "- In `Change to apply`, state the target file and purpose first.",
            "- In `Patch`, include a `diff` code block based only on disclosed code and context.",
            "- Mark removed lines with `-` and added lines with `+`. File headers, hunk headers, "
            "and exact line numbers are optional; do not claim the patch can be applied by Git.",
            "- Do not replace the diff with a full-file code block or infer hidden implementation.",
            "- Provide focused tests. If you did not run them, do not claim that they passed.",
            "- Limit `Needs confirmation` to two items. Where possible, support external API "
            "claims with versioned official documentation. Write `none` if nothing remains.",
            "- Unless requested otherwise, keep the answer within 80 non-empty lines.",
        )
    )


def _manifest_yaml(value: DisclosureManifest) -> str:
    return "\n".join(
        (
            "```yaml",
            "disclosure:",
            f"  schema_version: {value.schema_version}",
            f"  user_prompt: {value.user_prompt}",
            f"  relative_paths: {value.relative_paths}",
            f"  symbol_names: {value.symbol_names}",
            f"  public_imports: {value.public_imports}",
            f"  human_notes: {value.human_notes}",
            f"  human_notes_content: {value.human_notes_content}",
            f"  boundary_aliases: {value.boundary_aliases}",
            f"  source_delivery: {value.source_delivery}",
            f"  source_excerpts: {value.source_excerpts}",
            f"  source_lines: {value.source_lines}",
            f"  source_utf8_bytes: {value.source_utf8_bytes}",
            f"  source_content_mode: {value.source_content_mode}",
            f"  boundary_aliases_exposed_in_source: {value.boundary_aliases_exposed_in_source}",
            f"  renderer_added_absolute_paths: {value.renderer_added_absolute_paths}",
            f"  renderer_added_git_remotes: {value.renderer_added_git_remotes}",
            "```",
        )
    )


def _source_markdown(
    values: tuple[ApprovedSourceExcerpt, ...], *, language: Language
) -> str | None:
    if not values:
        return None
    introduction = (
        "이 문서에는 사용자가 외부 공개를 승인한 원문 코드가 포함되어 있습니다. "
        "주석, docstring, 문자열, 경로와 내부 식별자를 직접 확인하십시오."
        if language == "ko"
        else "This document includes verbatim source approved for external disclosure. Review "
        "comments, docstrings, strings, paths, and internal identifiers yourself."
    )
    parts = [introduction]
    for value in values:
        if language == "ko":
            kind = {"module": "파일(모듈)", "class": "클래스", "function": "함수"}[value.kind]
            aliases = ", ".join(value.boundary_aliases) or "없음"
            heading = (
                f"### {_code_span(value.path)} | "
                f"{_code_span(f'{kind} {value.qualified_name}')} | "
                f"{value.start_line}-{value.end_line}행"
            )
            approval = f"경계 식별자 공개 승인: {aliases}"
        else:
            aliases = ", ".join(value.boundary_aliases) or "none"
            heading = (
                f"### {_code_span(value.path)} — "
                f"{_code_span(f'{value.kind} {value.qualified_name}')} — "
                f"lines {value.start_line}-{value.end_line}"
            )
            approval = f"Boundary exposure approval: {aliases}"
        parts.extend(
            (
                "",
                heading,
                "",
                approval,
                "",
                _python_fence(value.content),
            )
        )
    return "\n".join(parts) + "\n"


def _python_fence(content: str) -> str:
    fence = "`" * max(3, _longest_backtick_run(content) + 1)
    separator = "" if content.endswith("\n") else "\n"
    return f"{fence}python\n{content}{separator}{fence}"


def _code_span(value: str) -> str:
    fence = "`" * max(1, _longest_backtick_run(value) + 1)
    return f"{fence}{value}{fence}"


def _longest_backtick_run(value: str) -> int:
    longest = 0
    current = 0
    for character in value:
        if character == "`":
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return longest
