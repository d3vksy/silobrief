from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import PurePosixPath, PureWindowsPath
from typing import Literal

from silobrief.index import NodeKind
from silobrief.source_excerpts import MAX_SOURCE_LINES, MAX_SOURCE_UTF8_BYTES
from silobrief.source_review import ApprovedSourceExcerpt

_KIND_ORDER = {"module": 0, "class": 1, "function": 2}
_WARNING = (
    "승인한 source 원문에는 자동으로 분류하지 못한 식별자, 경로, URL, 문자열 또는 "
    "비밀정보가 포함될 수 있습니다. siloBrief는 보안 검사나 반출 승인을 보장하지 "
    "않으므로 두 파일 전체를 직접 확인해야 합니다."
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
    source_companion: str | None
    source_excerpts: tuple[ApprovedSourceExcerpt, ...]


@dataclass(frozen=True, slots=True)
class DisclosureManifest:
    schema_version: Literal[2]
    user_prompt: Literal["included"]
    relative_paths: int
    symbol_names: int
    public_imports: int
    human_notes: int
    human_notes_content: Literal["user-supplied-unclassified"]
    boundary_aliases: int
    source_companion: str
    source_excerpts: int
    source_lines: int
    source_utf8_bytes: int
    source_content_mode: Literal["verbatim", "none"]
    boundary_aliases_exposed_in_source: int
    renderer_added_absolute_paths: Literal[0]
    renderer_added_git_remotes: Literal[0]


@dataclass(frozen=True, slots=True)
class RenderedBrief:
    main_markdown: str
    source_markdown: str | None
    disclosure: DisclosureManifest


def render_brief(source: BriefInput) -> RenderedBrief:
    approved = _prepare(source)
    disclosure = _disclosure(approved)
    sections = (
        _section(
            "경고와 공개 범위",
            "이 문서는 사용자가 승인한 프로젝트 맥락만 담습니다. 숨긴 구현을 추측하거나 "
            f"공개 범위를 보안 보장으로 해석하면 안 됩니다.\n\n{_WARNING}",
        ),
        _section("작업 요청", _quote(approved.user_prompt)),
        _section("승인된 프로젝트 맥락", _project_context(approved)),
        _section("사용자 작성 메모", _quoted_list(approved.human_notes)),
        _section("등록된 경계", _boundary_list(approved.boundaries)),
        _section("소스 동반 파일", _source_companion_section(approved.source_companion)),
        _section("외부 AI 응답 계약", _response_contract()),
        _section("외부 AI에 전달할 요청", _copy_prompt(approved)),
        _section("Disclosure manifest", _manifest_yaml(disclosure)),
        _section("수동 확인 체크리스트", _manual_checklist(approved.source_companion)),
    )
    return RenderedBrief(
        main_markdown="\n\n".join(sections) + "\n",
        source_markdown=_source_markdown(approved.source_excerpts),
        disclosure=disclosure,
    )


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
    companion = _source_companion(source.source_companion)
    if bool(excerpts) != (companion is not None):
        raise RenderError("source companion and source excerpts must be provided together")
    return BriefInput(
        prompt,
        paths,
        symbols,
        public_imports,
        notes,
        boundaries,
        companion,
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


def _source_companion(value: object) -> str | None:
    if value is None:
        return None
    name = _single_line(value, "source companion")
    if (
        "/" in name
        or "\\" in name
        or PurePosixPath(name).name != name
        or not name.endswith(".sources.md")
    ):
        raise RenderError("source companion must be a .sources.md file name")
    return name


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
        schema_version=2,
        user_prompt="included",
        relative_paths=len(source.relative_paths),
        symbol_names=len(source.symbols),
        public_imports=len(source.public_imports),
        human_notes=len(source.human_notes),
        human_notes_content="user-supplied-unclassified",
        boundary_aliases=len(source.boundaries),
        source_companion=source.source_companion or "none",
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


def _quote(value: str) -> str:
    return "\n".join(">" if not line else f"> {line}" for line in value.split("\n"))


def _quoted_list(values: tuple[str, ...]) -> str:
    if not values:
        return "- 없음"
    lines: list[str] = []
    for value in values:
        lines.append("- 승인 항목:")
        lines.extend(f"  {line}" for line in _quote(value).splitlines())
    return "\n".join(lines)


def _project_context(source: BriefInput) -> str:
    symbols = tuple(f"{item.kind}: {item.name}" for item in source.symbols)
    return "\n\n".join(
        (
            f"### 상대 경로\n\n{_quoted_list(source.relative_paths)}",
            f"### 심볼\n\n{_quoted_list(symbols)}",
            f"### 공개 import\n\n{_quoted_list(source.public_imports)}",
        )
    )


def _boundary_list(values: tuple[ApprovedBoundary, ...]) -> str:
    if not values:
        return "- 없음"
    lines: list[str] = []
    for value in values:
        lines.extend(("- 경계 alias:", f"  {_quote(value.alias)}", "  공개 설명:"))
        lines.extend(f"  {line}" for line in _quote(value.description).splitlines())
    return "\n".join(lines)


def _source_companion_section(value: str | None) -> str:
    if value is None:
        return "- 없음"
    return (
        f"- 파일: {_code_span(value)}\n"
        "- main brief와 이 파일을 함께 전달해야 합니다.\n"
        "- 파일이 누락되면 숨은 코드를 추측하지 말고 누락 사실을 알려야 합니다."
    )


def _response_contract() -> str:
    return "\n".join(
        (
            "1. 긴 서론 없이 적용할 변경부터 제시합니다.",
            "2. 첫 8개 비어 있지 않은 줄 안에 대상 파일과 변경 목적을 표시합니다.",
            "3. 제공된 코드와 공개 맥락만 근거로 patch 또는 교체 코드를 작성합니다.",
            "4. 숨긴 프로젝트 구조·필드·함수·호출 방식을 추측하지 않습니다.",
            "5. 변경 동작을 검증하는 테스트를 함께 제시합니다.",
            "6. 실제 실행하지 않은 테스트를 실행했다고 표현하지 않습니다.",
            "7. 추가 확인은 최대 2개만 적습니다.",
            "8. 외부 API 주장은 가능한 경우 버전 고정 공식 문서를 근거로 합니다.",
            "9. 별도 요구가 없으면 비어 있지 않은 줄 80개 이내로 답합니다.",
            "",
            "권장 응답 제목:",
            "",
            "```text",
            "## 바로 적용할 변경",
            "## 패치 또는 교체 코드",
            "## 테스트",
            "## 확인 필요",
            "```",
        )
    )


def _copy_prompt(source: BriefInput) -> str:
    companion = source.source_companion or "제공된 source companion 없음"
    delivery = "두 Markdown 파일" if source.source_companion is not None else "이 Markdown 파일"
    text = "\n".join(
        (
            "아래 작업을 공개된 프로젝트 맥락과 source만 사용해 수행하세요.",
            "작업 요청:",
            source.user_prompt,
            f"source companion: {companion}",
            "숨긴 구현을 추측하지 말고 위 응답 계약을 지키세요.",
            "외부 API 사실은 가능한 경우 버전이 고정된 공식 문서 URL로 뒷받침하세요.",
        )
    )
    return (
        f"이 요청은 사용자가 {delivery}과 함께 복사하는 용도입니다. siloBrief는 "
        f"외부 AI를 호출하거나 전송하지 않습니다.\n\n{_quote(text)}"
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
            f"  source_companion: {_yaml_text(value.source_companion)}",
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


def _manual_checklist(companion: str | None) -> str:
    companion_item = (
        "- [ ] main과 source companion을 함께 전달했습니다."
        if companion is not None
        else "- [ ] source companion이 없는 실행임을 확인했습니다."
    )
    return "\n".join(
        (
            "- [ ] 작업 요청이 외부에 공개 가능한지 확인했습니다.",
            "- [ ] 승인한 경로·심볼·메모·경계 설명을 확인했습니다.",
            companion_item,
            "- [ ] source 원문에 의도하지 않은 정보가 없는지 확인했습니다.",
            "- [ ] 외부 AI가 공개되지 않은 구현을 추측하지 않았는지 확인할 예정입니다.",
        )
    )


def _source_markdown(values: tuple[ApprovedSourceExcerpt, ...]) -> str | None:
    if not values:
        return None
    parts = [
        "# Approved source excerpts",
        "",
        "이 파일에는 사용자가 외부 공개를 승인한 원문 코드가 포함되어 있습니다. "
        "주석, docstring, 문자열, 경로와 내부 식별자를 직접 확인하십시오.",
    ]
    for value in values:
        aliases = ", ".join(value.boundary_aliases) or "none"
        parts.extend(
            (
                "",
                f"## {_code_span(value.path)} — "
                f"{_code_span(f'{value.kind} {value.qualified_name}')} — "
                f"lines {value.start_line}-{value.end_line}",
                "",
                f"Boundary exposure approval: {aliases}",
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


def _yaml_text(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)
