from __future__ import annotations

import argparse
import sys
import unicodedata
from collections.abc import Sequence
from pathlib import Path
from typing import TextIO

from silobrief import __version__
from silobrief.boundaries import register_boundary, unregister_boundary
from silobrief.candidate_search import (
    CandidateSearchError,
    render_candidate_results,
    search_candidates,
)
from silobrief.chat_review import ChatReviewError, review_brief
from silobrief.current_index import CurrentIndexError, load_current_index
from silobrief.example_project import ExampleProjectError, create_example_project
from silobrief.initialization import (
    IndexingError,
    InitProgress,
    SourceChangedError,
    initialize_index,
)
from silobrief.language import Language, LanguageSettings, localized, parse_language
from silobrief.notes import add_note
from silobrief.output import OutputBlockedError, approve_and_write
from silobrief.sources import SourceCollectionError
from silobrief.state import (
    IndexStateError,
    SetupError,
    find_project_root,
    load_language_settings,
    load_notes,
    save_language_settings,
    setup_project,
)
from silobrief.stored_index import StoredIndexError

_SOURCE_DISCLOSURE_WARNING_EN = (
    "warning: non-ignored Python files are analyzed locally; source excerpts you select and "
    "approve may be exported verbatim with comments, docstrings, strings, and internal "
    "identifiers. siloBrief does not detect secrets or provide security approval; review all "
    "output yourself."
)
_SOURCE_DISCLOSURE_WARNING_KO = (
    "경고: 무시하지 않은 Python 파일은 로컬에서 분석됩니다. 사용자가 선택하고 승인한 "
    "소스 발췌는 주석, docstring, 문자열과 내부 식별자를 포함한 원문 그대로 내보낼 수 "
    "있습니다. siloBrief는 비밀정보를 탐지하거나 보안 승인을 제공하지 않습니다. 모든 "
    "출력을 직접 검토하세요."
)

_INIT_PROGRESS_WIDTH = 20


class _InitProgressBar:
    def __init__(self, stream: TextIO, language: Language) -> None:
        self._stream = stream
        self._language = language
        self._last_width = 0
        self._active = False

    def update(self, progress: InitProgress) -> None:
        filled = _INIT_PROGRESS_WIDTH * progress.completed // progress.total
        bar = "#" * filled + "-" * (_INIT_PROGRESS_WIDTH - filled)
        percent = 100 * progress.completed // progress.total
        line = f"sb init [{bar}] {percent:3d}% {_init_progress_label(progress, self._language)}"
        line_width = _terminal_width(line)
        padding = " " * max(0, self._last_width - line_width)
        self._stream.write(f"\r{line}{padding}")
        self._stream.flush()
        self._last_width = line_width
        self._active = progress.phase != "complete"
        if not self._active:
            self._stream.write("\n")
            self._stream.flush()

    def finish(self) -> None:
        if self._active:
            self._stream.write("\n")
            self._stream.flush()
            self._active = False


def _terminal_width(value: str) -> int:
    width = 0
    for character in value:
        if unicodedata.combining(character):
            continue
        width += 2 if unicodedata.east_asian_width(character) in {"F", "W"} else 1
    return width


def _init_progress_label(progress: InitProgress, language: Language) -> str:
    source_files = progress.source_files if progress.source_files is not None else 0
    file_label = "file" if source_files == 1 else "files"
    if progress.phase == "collecting":
        return localized(language, "Collecting allowed Python files", "허용된 Python 파일 수집 중")
    if progress.phase == "analyzing":
        return localized(
            language,
            f"Analyzing {source_files} Python {file_label}",
            f"Python 파일 {source_files}개 분석 중",
        )
    if progress.phase == "building":
        return localized(language, "Building local index", "로컬 색인 생성 중")
    if progress.phase == "verifying":
        return localized(language, "Checking for source changes", "소스 변경 여부 확인 중")
    if progress.phase == "writing":
        return localized(
            language,
            "Writing .silobrief/index.json",
            ".silobrief/index.json 저장 중",
        )
    return localized(
        language,
        f"Indexed {source_files} Python {file_label}",
        f"Python 파일 {source_files}개 색인 완료",
    )


def _build_parser(language: Language = "en") -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sb",
        description=localized(
            language,
            "Create a reviewed research brief from Python project context.",
            "Python 프로젝트 맥락으로 검토된 작업 브리프를 만듭니다.",
        ),
    )
    parser.add_argument("--version", action="version", version=f"siloBrief {__version__}")
    subcommands = parser.add_subparsers(dest="command", required=True)
    setup = subcommands.add_parser(
        "setup",
        help=localized(
            language, "Initialize local project state.", "로컬 프로젝트 상태를 만듭니다."
        ),
    )
    setup.add_argument("path", nargs="?", type=Path, default=Path.cwd())
    example = subcommands.add_parser(
        "example",
        help=localized(
            language, "Create a guided practice project.", "실습용 예제 프로젝트를 만듭니다."
        ),
    )
    example.add_argument("path", type=Path)
    ignore = subcommands.add_parser(
        "ignore",
        help=localized(
            language, "Register a project boundary.", "프로젝트 공개 경계를 등록합니다."
        ),
    )
    ignore.add_argument("path")
    ignore.add_argument("--as", dest="description", required=True)
    ignore.add_argument("--alias")
    unignore = subcommands.add_parser(
        "unignore",
        help=localized(
            language, "Remove a registered project boundary.", "등록한 공개 경계를 제거합니다."
        ),
    )
    unignore.add_argument("selector")
    subcommands.add_parser(
        "init",
        help=localized(language, "Build the local source index.", "로컬 소스 인덱스를 만듭니다."),
    )
    log = subcommands.add_parser(
        "log",
        help=localized(
            language, "Record public project context.", "공개 가능한 프로젝트 메모를 기록합니다."
        ),
    )
    log.add_argument("path")
    log.add_argument("--comment", required=True)
    search = subcommands.add_parser(
        "search",
        help=localized(
            language, "Find candidate code for a request.", "요청과 관련된 코드 후보를 찾습니다."
        ),
    )
    search.add_argument("prompt")
    language_parser = subcommands.add_parser(
        "language",
        help=localized(
            language, "Configure CLI and brief languages.", "CLI와 브리프 언어를 설정합니다."
        ),
    )
    language_parser.add_argument("--cli", dest="cli_language", choices=("en", "ko"))
    language_parser.add_argument("--brief", dest="brief_language", choices=("en", "ko"))
    brief = subcommands.add_parser(
        "brief",
        help=localized(
            language, "Create a reviewed research brief.", "검토 후 작업 브리프를 만듭니다."
        ),
    )
    brief.add_argument("prompt")
    brief.add_argument("--out", dest="output", required=True)
    chat = subcommands.add_parser(
        "chat",
        help=localized(
            language,
            "Deprecated alias for 'brief'.",
            "'brief' 명령의 사용 중단 예정 별칭입니다.",
        ),
    )
    chat.add_argument("prompt")
    chat.add_argument("--out", dest="output", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    cli_language = _detect_cli_language(Path.cwd())
    parser = _build_parser(cli_language)
    arguments = parser.parse_args(argv)

    if arguments.command == "example":
        project = arguments.path
        if not isinstance(project, Path):
            parser.error(
                localized(
                    cli_language,
                    "example path must be a filesystem path",
                    "예제 경로는 파일 시스템 경로여야 합니다",
                )
            )
        try:
            file_count = create_example_project(project)
        except ExampleProjectError as error:
            parser.error(str(error))
        print(
            localized(
                cli_language,
                f"created example project with {file_count} files at {project}",
                f"{project}에 파일 {file_count}개로 예제 프로젝트를 만들었습니다",
            )
        )
        print(
            localized(
                cli_language,
                "next: enter that directory and run sb setup .",
                "다음: 해당 디렉터리에서 sb setup . 을 실행하세요",
            )
        )

    if arguments.command == "setup":
        project = arguments.path
        if not isinstance(project, Path):
            parser.error(
                localized(
                    cli_language,
                    "setup path must be a filesystem path",
                    "설정 경로는 파일 시스템 경로여야 합니다",
                )
            )
        try:
            created = setup_project(project)
        except SetupError as error:
            parser.error(str(error))
        try:
            cli_language = load_language_settings(project.resolve(strict=True))["cli_language"]
        except (OSError, SetupError):
            pass
        if created:
            print(
                localized(
                    cli_language,
                    "created .silobrief/config.json, .silobrief/notes.json, "
                    ".silobrief/language.json, and .silobrief/exports/",
                    ".silobrief/config.json, .silobrief/notes.json, "
                    ".silobrief/language.json과 .silobrief/exports/를 만들었습니다",
                )
            )
        else:
            print(
                localized(
                    cli_language,
                    "validated existing .silobrief state",
                    "기존 .silobrief 상태를 확인했습니다",
                )
            )
        print(
            localized(
                cli_language,
                _SOURCE_DISCLOSURE_WARNING_EN,
                _SOURCE_DISCLOSURE_WARNING_KO,
            )
        )

    if arguments.command == "ignore":
        path_text = arguments.path
        description = arguments.description
        alias = arguments.alias
        if not isinstance(path_text, str) or not isinstance(description, str):
            parser.error(
                localized(
                    cli_language,
                    "ignore path and description must be text",
                    "무시 경로와 설명은 텍스트여야 합니다",
                )
            )
        if alias is not None and not isinstance(alias, str):
            parser.error(
                localized(
                    cli_language, "ignore alias must be text", "무시 alias는 텍스트여야 합니다"
                )
            )
        try:
            registration = register_boundary(path_text, description, alias, start=Path.cwd())
        except SetupError as error:
            parser.error(str(error))
        boundary = registration.boundary
        if registration.changed:
            print(
                localized(
                    cli_language,
                    f"registered boundary {boundary['alias']} for {boundary['path']}; "
                    "updated .silobrief/config.json",
                    f"{boundary['path']}에 경계 {boundary['alias']}를 등록하고 "
                    ".silobrief/config.json을 갱신했습니다",
                )
            )
        else:
            print(
                localized(
                    cli_language,
                    f"boundary {boundary['alias']} for {boundary['path']} is already registered",
                    f"{boundary['path']}의 경계 {boundary['alias']}는 이미 등록되어 있습니다",
                )
            )

    if arguments.command == "unignore":
        selector = arguments.selector
        if not isinstance(selector, str):
            parser.error(
                localized(
                    cli_language,
                    "unignore selector must be text",
                    "경계 선택자는 텍스트여야 합니다",
                )
            )
        try:
            boundary = unregister_boundary(selector, start=Path.cwd())
        except SetupError as error:
            parser.error(str(error))
        print(
            localized(
                cli_language,
                f"removed boundary {boundary['alias']} for {boundary['path']}; "
                "run sb init before sb brief",
                f"{boundary['path']}의 경계 {boundary['alias']}를 제거했습니다. "
                "sb brief 전에 sb init을 실행하세요",
            )
        )

    if arguments.command == "init":
        progress_bar = _InitProgressBar(sys.stderr, cli_language) if sys.stderr.isatty() else None
        try:
            warnings = initialize_index(
                Path.cwd(),
                progress=progress_bar.update if progress_bar is not None else None,
            )
        except SetupError as error:
            if progress_bar is not None:
                progress_bar.finish()
            parser.error(str(error))
        except IndexingError as error:
            if progress_bar is not None:
                progress_bar.finish()
            print(f"sb: {localized(cli_language, 'error', '오류')}: {error}", file=sys.stderr)
            return 3
        except SourceChangedError as error:
            if progress_bar is not None:
                progress_bar.finish()
            print(f"sb: {localized(cli_language, 'error', '오류')}: {error}", file=sys.stderr)
            return 4
        for warning in warnings:
            print(
                f"{localized(cli_language, 'warning', '경고')}: {warning.path}: {warning.reason}",
                file=sys.stderr,
            )
        print(
            localized(
                cli_language, "built .silobrief/index.json", ".silobrief/index.json을 만들었습니다"
            )
        )

    if arguments.command == "log":
        path_text = arguments.path
        comment = arguments.comment
        if not isinstance(path_text, str) or not isinstance(comment, str):
            parser.error(
                localized(
                    cli_language,
                    "log path and comment must be text",
                    "메모 경로와 내용은 텍스트여야 합니다",
                )
            )
        if not comment.strip():
            parser.error(
                localized(
                    cli_language,
                    "note comment must not be empty",
                    "메모 내용은 비어 있을 수 없습니다",
                )
            )
        print(
            localized(
                cli_language,
                "warning: this comment may be included in the final brief",
                "경고: 이 메모는 최종 브리프에 포함될 수 있습니다",
            ),
            file=sys.stderr,
        )
        try:
            note = add_note(path_text, comment, start=Path.cwd())
        except SetupError as error:
            parser.error(str(error))
        print(
            localized(
                cli_language,
                f"recorded note {note['id']} for {note['path']}; updated .silobrief/notes.json",
                f"{note['path']}에 메모 {note['id']}를 기록하고 "
                ".silobrief/notes.json을 갱신했습니다",
            )
        )

    if arguments.command == "language":
        start = Path.cwd()
        try:
            root = find_project_root(start)
            settings = load_language_settings(root)
            cli_value = arguments.cli_language
            brief_value = arguments.brief_language
            updated = LanguageSettings(
                brief_language=(
                    parse_language(brief_value)
                    if brief_value is not None
                    else settings["brief_language"]
                ),
                cli_language=(
                    parse_language(cli_value) if cli_value is not None else settings["cli_language"]
                ),
                settings_version=1,
            )
            if updated != settings:
                save_language_settings(root, updated)
        except (SetupError, ValueError) as error:
            parser.error(str(error))
        cli_language = updated["cli_language"]
        print(localized(cli_language, f"CLI language: {cli_language}", f"CLI 언어: {cli_language}"))
        print(
            localized(
                cli_language,
                f"Brief language: {updated['brief_language']}",
                f"브리프 언어: {updated['brief_language']}",
            )
        )

    if arguments.command == "search":
        prompt = arguments.prompt
        if not isinstance(prompt, str) or not prompt.strip():
            parser.error(
                localized(cli_language, "request must not be empty", "요청은 비어 있을 수 없습니다")
            )

        start = Path.cwd()
        try:
            root = find_project_root(start)
            index, snapshot = load_current_index(root)
            notes = load_notes(root)
            settings = load_language_settings(root)
            cli_language = settings["cli_language"]
            search_output = render_candidate_results(
                search_candidates(prompt, index, notes), language=cli_language
            )
        except IndexStateError as error:
            print(f"sb: {localized(cli_language, 'error', '오류')}: {error}", file=sys.stderr)
            return 3
        except SetupError as error:
            parser.error(str(error))
        except StoredIndexError as error:
            print(f"sb: {localized(cli_language, 'error', '오류')}: {error}", file=sys.stderr)
            return 3
        except (CurrentIndexError, SourceCollectionError, CandidateSearchError) as error:
            print(f"sb: {localized(cli_language, 'error', '오류')}: {error}", file=sys.stderr)
            return 4

        for warning in snapshot.warnings:
            print(
                f"{localized(cli_language, 'warning', '경고')}: {warning.path}: {warning.reason}",
                file=sys.stderr,
            )
        print(search_output, end="")

    if arguments.command in {"brief", "chat"}:
        if arguments.command == "chat":
            print(
                localized(
                    cli_language,
                    "sb chat is deprecated; use sb brief instead",
                    "sb chat은 사용 중단 예정입니다. 대신 sb brief를 사용하세요",
                ),
                file=sys.stderr,
            )
        prompt = arguments.prompt
        output_text = arguments.output
        if not isinstance(prompt, str) or not prompt.strip():
            parser.error(
                localized(cli_language, "request must not be empty", "요청은 비어 있을 수 없습니다")
            )
        if not isinstance(output_text, str) or not output_text.strip():
            parser.error(
                localized(
                    cli_language,
                    "output path must not be empty",
                    "출력 경로는 비어 있을 수 없습니다",
                )
            )

        start = Path.cwd()
        try:
            root = find_project_root(start)
            index, snapshot = load_current_index(root)
            notes = load_notes(root)
            settings = load_language_settings(root)
            cli_language = settings["cli_language"]
        except IndexStateError as error:
            print(f"sb: {localized(cli_language, 'error', '오류')}: {error}", file=sys.stderr)
            return 3
        except SetupError as error:
            parser.error(str(error))
        except StoredIndexError as error:
            print(f"sb: {localized(cli_language, 'error', '오류')}: {error}", file=sys.stderr)
            return 3
        except (CurrentIndexError, SourceCollectionError) as error:
            print(f"sb: {localized(cli_language, 'error', '오류')}: {error}", file=sys.stderr)
            return 4

        for warning in snapshot.warnings:
            print(
                f"{localized(cli_language, 'warning', '경고')}: {warning.path}: {warning.reason}",
                file=sys.stderr,
            )
        try:
            rendered = review_brief(
                prompt,
                index,
                notes,
                input_stream=sys.stdin,
                output_stream=sys.stdout,
                snapshot=snapshot,
                brief_language=settings["brief_language"],
                cli_language=cli_language,
            )
            approve_and_write(
                root,
                output_text,
                rendered,
                start=start,
                input_stream=sys.stdin,
                output_stream=sys.stdout,
                source_snapshot=snapshot,
                language=cli_language,
            )
        except (ChatReviewError, OutputBlockedError) as error:
            print(f"sb: {localized(cli_language, 'error', '오류')}: {error}", file=sys.stderr)
            return 4
        print(
            localized(cli_language, f"\nwrote {output_text}", f"\n{output_text}을(를) 작성했습니다")
        )

    return 0


def _detect_cli_language(start: Path) -> Language:
    try:
        root = find_project_root(start)
        return load_language_settings(root)["cli_language"]
    except SetupError:
        return "en"
