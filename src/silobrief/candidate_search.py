from __future__ import annotations

from silobrief.index import IndexData
from silobrief.language import Language, localized
from silobrief.ranking import RankEvidence, rank_candidates
from silobrief.review import CandidateOption, ReviewError, candidate_options
from silobrief.state import NotesData
from silobrief.terminal import styled


class CandidateSearchError(ValueError):
    pass


def search_candidates(
    prompt: str,
    index: IndexData,
    notes: NotesData,
) -> tuple[CandidateOption, ...]:
    if not prompt.strip():
        raise CandidateSearchError("request must not be empty")
    try:
        return candidate_options(rank_candidates(prompt, index, notes))
    except ReviewError as error:
        raise CandidateSearchError(str(error)) from error


def render_candidate_results(
    options: tuple[CandidateOption, ...],
    *,
    language: Language = "en",
    color: bool = False,
    interactive: bool = False,
) -> str:
    lines = [
        styled(localized(language, "Candidates:", "코드 후보:"), "1;36", enabled=color),
        localized(
            language,
            "These files, functions, and classes appear related to the request.",
            "요청과 관련 있어 보이는 파일, 함수, 클래스입니다.",
        ),
        localized(
            language,
            "If names are repeated, compare their file paths.",
            "같은 이름이 여러 번 나오면 파일 경로를 비교하세요.",
        ),
        localized(
            language,
            "Relevance is based on matching names, paths, code descriptions, notes, and "
            "connections.",
            "관련도는 이름, 파일 경로, 코드 설명, 메모, 연결 관계를 바탕으로 계산합니다.",
        ),
    ]
    if interactive:
        lines.append(
            localized(
                language,
                "Choose what to include in the brief. If nothing fits, press Enter and enter "
                "a file path directly.",
                "문서에 넣을 항목을 고르세요. 원하는 항목이 없으면 Enter를 누른 뒤 "
                "파일 경로로 직접 찾을 수 있습니다.",
            )
        )
    lines.append("")
    if not options:
        lines.append(
            localized(language, "No matching code was found.", "일치하는 코드를 찾지 못했습니다.")
        )
    for option in options:
        node = option.node
        lines.append(
            f"{styled(f'[{option.number}]', '1;32', enabled=color)} "
            f"{_render_kind(node.kind, language=language)} "
            f"{styled(node.qualified_name, '1', enabled=color)}"
        )
        lines.append(f"    {localized(language, 'File', '파일')}: {node.path}")
        lines.append(
            f"    {localized(language, 'Why it matched', '찾은 이유')}: "
            f"{_render_matches(option.evidence, language=language)}"
        )
        lines.append(
            f"    {localized(language, 'Relevance', '관련도')}: "
            f"{styled(str(option.score), '1;33', enabled=color)}"
            f"{localized(language, ' points', '점')}"
            f"  |  {localized(language, 'Directly connected items', '직접 연결된 코드')}: "
            f"{option.evidence.connected_nodes}{localized(language, '', '개')}"
        )
        lines.append("")
    return "\n".join(lines) + "\n"


def _render_matches(evidence: RankEvidence, *, language: Language) -> str:
    fields = (
        (localized(language, "file path", "파일 경로"), evidence.path_matches),
        (localized(language, "name", "이름"), evidence.symbol_matches),
        ("import", evidence.import_matches),
        (localized(language, "code description", "코드 설명"), evidence.docstring_matches),
        (localized(language, "comment", "주석"), evidence.comment_matches),
        (localized(language, "user note", "사용자 메모"), evidence.note_matches),
    )
    grouped: dict[tuple[str, ...], list[str]] = {}
    for label, tokens in fields:
        if tokens:
            grouped.setdefault(tokens, []).append(label)
    matches = [
        localized(
            language,
            f"{_english_join(labels)} {'contains' if len(labels) == 1 else 'contain'} "
            f'"{", ".join(tokens)}"',
            f'{", ".join(labels)}에서 "{", ".join(tokens)}" 일치',
        )
        for tokens, labels in grouped.items()
    ]
    return "; ".join(matches) if matches else localized(language, "none", "없음")


def _english_join(values: list[str]) -> str:
    if len(values) == 1:
        return values[0]
    if len(values) == 2:
        return " and ".join(values)
    return f"{', '.join(values[:-1])}, and {values[-1]}"


def _render_kind(kind: str, *, language: Language) -> str:
    labels = {
        "module": localized(language, "module", "파일(모듈)"),
        "class": localized(language, "class", "클래스"),
        "function": localized(language, "function", "함수"),
    }
    return labels[kind]
