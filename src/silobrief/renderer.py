from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath, PureWindowsPath
from typing import Literal

from silobrief.index import NodeKind

_KIND_ORDER = {"module": 0, "class": 1, "function": 2}
_WARNING = (
    "경로 단위 ignore는 허용된 파일 안에 있는 민감한 식별자를 보호하지 못합니다. "
    "이 산출물은 자동 보안 검사를 통과한 문서가 아니며 이동 전에 사람이 전체 내용을 "
    "확인해야 합니다."
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
    public_dependencies: tuple[str, ...]
    human_notes: tuple[str, ...]
    boundaries: tuple[ApprovedBoundary, ...]


@dataclass(frozen=True, slots=True)
class DisclosureManifest:
    user_prompt: Literal["included"]
    relative_paths: int
    symbol_names: int
    public_dependencies: int
    human_notes: int
    boundary_aliases: int
    source_bodies: int
    comments: int
    docstrings: int
    string_literals: int
    absolute_paths: int
    git_remotes: int
    ignored_real_names: int


@dataclass(frozen=True, slots=True)
class RenderedBrief:
    markdown: str
    disclosure: DisclosureManifest


def render_brief(source: BriefInput) -> RenderedBrief:
    approved = _prepare(source)
    disclosure = _disclosure(approved)
    sections = (
        _section(
            "경고와 용도",
            "이 브리프는 공식 문서 조사를 준비하는 보조 자료이며 보안 인증이나 반출 "
            f"승인이 아닙니다.\n\n{_WARNING}",
        ),
        _section("원래 작업 요청", _quote(approved.user_prompt)),
        _section("선택한 프로젝트 맥락", _project_context(approved)),
        _section("사용자 작성 메모", _quoted_list(approved.human_notes)),
        _section("숨긴 경계", _boundary_list(approved.boundaries)),
        _section("조사 질문", _research_questions()),
        _section("추천 검색어", _quoted_list(_search_terms(approved))),
        _section("외부 AI에 복사할 프롬프트", _copy_prompt(approved)),
        _section("Disclosure manifest", _manifest_yaml(disclosure)),
        _section("수동 확인 체크리스트", _manual_checklist()),
    )
    return RenderedBrief(markdown="\n\n".join(sections) + "\n", disclosure=disclosure)


def _prepare(source: BriefInput) -> BriefInput:
    if type(source) is not BriefInput:
        raise RenderError("renderer accepts only the BriefInput whitelist")
    prompt = _text(source.user_prompt, "user prompt")
    paths = tuple(sorted({_relative_path(value) for value in source.relative_paths}))
    symbols = _symbols(source.symbols)
    dependencies = tuple(
        sorted({_single_line(value, "public dependency") for value in source.public_dependencies})
    )
    notes = tuple(_text(value, "human note") for value in source.human_notes)
    boundaries = _boundaries(source.boundaries)
    return BriefInput(prompt, paths, symbols, dependencies, notes, boundaries)


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
    return DisclosureManifest(
        user_prompt="included",
        relative_paths=len(source.relative_paths),
        symbol_names=len(source.symbols),
        public_dependencies=len(source.public_dependencies),
        human_notes=len(source.human_notes),
        boundary_aliases=len(source.boundaries),
        source_bodies=0,
        comments=0,
        docstrings=0,
        string_literals=0,
        absolute_paths=0,
        git_remotes=0,
        ignored_real_names=0,
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
            f"### 공개 라이브러리\n\n{_quoted_list(source.public_dependencies)}",
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


def _research_questions() -> str:
    return "\n".join(
        (
            "1. 원래 작업 요청을 해결하려면 어떤 공식 문서 항목을 확인해야 하는가?",
            "2. 선택한 프로젝트 맥락에 적용되는 공개 API와 제약은 무엇인가?",
            "3. 답변의 근거가 되는 공식 문서 URL과 적용 조건은 무엇인가?",
        )
    )


def _search_terms(source: BriefInput) -> tuple[str, ...]:
    seeds = (
        source.user_prompt,
        *source.relative_paths,
        *(item.name for item in source.symbols),
        *source.public_dependencies,
    )
    result: list[str] = []
    seen: set[str] = set()
    for seed in seeds:
        term = f"{' '.join(seed.split())} official documentation"
        if term not in seen:
            seen.add(term)
            result.append(term)
    return tuple(result)


def _copy_prompt(source: BriefInput) -> str:
    symbols = tuple(f"{item.kind}: {item.name}" for item in source.symbols)
    boundaries = tuple(f"{item.alias}: {item.description}" for item in source.boundaries)
    text = "\n".join(
        (
            "공식 문서만 사용해 아래 작업을 조사하세요.",
            "작업 요청:",
            source.user_prompt,
            f"상대 경로: {_joined(source.relative_paths)}",
            f"심볼: {_joined(symbols)}",
            f"공개 라이브러리: {_joined(source.public_dependencies)}",
            f"사용자 작성 메모: {_joined(source.human_notes)}",
            f"숨긴 경계: {_joined(boundaries)}",
            "확인하지 못한 내용은 추측하지 말고 공식 문서 URL을 제시하세요.",
        )
    )
    return (
        "이 템플릿은 사용자가 선택적으로 복사하는 용도이며 siloBrief는 외부 AI를 "
        f"호출하거나 전송하지 않습니다.\n\n{_quote(text)}"
    )


def _joined(values: tuple[str, ...]) -> str:
    return " | ".join(" ".join(value.split()) for value in values) or "제공된 항목 없음"


def _manifest_yaml(value: DisclosureManifest) -> str:
    return "\n".join(
        (
            "```yaml",
            "disclosure:",
            f"  user_prompt: {value.user_prompt}",
            f"  relative_paths: {value.relative_paths}",
            f"  symbol_names: {value.symbol_names}",
            f"  public_dependencies: {value.public_dependencies}",
            f"  human_notes: {value.human_notes}",
            f"  boundary_aliases: {value.boundary_aliases}",
            f"  source_bodies: {value.source_bodies}",
            f"  comments: {value.comments}",
            f"  docstrings: {value.docstrings}",
            f"  string_literals: {value.string_literals}",
            f"  absolute_paths: {value.absolute_paths}",
            f"  git_remotes: {value.git_remotes}",
            f"  ignored_real_names: {value.ignored_real_names}",
            "```",
        )
    )


def _manual_checklist() -> str:
    return "\n".join(
        (
            "- [ ] 원래 작업 요청이 외부에 공개 가능한지 확인했습니다.",
            "- [ ] 선택한 경로·심볼·메모·경계 설명을 모두 확인했습니다.",
            "- [ ] 숨겨야 할 실제 이름이나 민감한 식별자가 없는지 확인했습니다.",
            "- [ ] 조사 결과가 공식 문서에 근거하는지 직접 확인할 예정입니다.",
            "- [ ] 이동 또는 공유 전에 이 Markdown 전체를 다시 검토합니다.",
        )
    )
