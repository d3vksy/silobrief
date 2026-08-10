from __future__ import annotations

from typing import Literal, TypedDict

Language = Literal["en", "ko"]
SUPPORTED_LANGUAGES: tuple[Language, ...] = ("en", "ko")


class LanguageSettings(TypedDict):
    brief_language: Language
    cli_language: Language
    settings_version: int


def default_language_settings() -> LanguageSettings:
    return LanguageSettings(
        brief_language="en",
        cli_language="en",
        settings_version=1,
    )


def parse_language(value: object) -> Language:
    if not isinstance(value, str) or value not in SUPPORTED_LANGUAGES:
        raise ValueError("language must be en or ko")
    return value


def parse_language_settings(value: dict[str, object]) -> LanguageSettings:
    if set(value) != {"brief_language", "cli_language", "settings_version"}:
        raise ValueError("language.json has an incompatible schema")
    if type(value["settings_version"]) is not int or value["settings_version"] != 1:
        raise ValueError("language.json has an unsupported version")
    try:
        brief_language = parse_language(value["brief_language"])
        cli_language = parse_language(value["cli_language"])
    except ValueError as error:
        raise ValueError("language.json languages must be en or ko") from error
    return LanguageSettings(
        brief_language=brief_language,
        cli_language=cli_language,
        settings_version=1,
    )


def localized(language: Language, english: str, korean: str) -> str:
    return korean if language == "ko" else english
