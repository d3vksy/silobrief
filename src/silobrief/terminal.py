from __future__ import annotations

import os
from typing import TextIO

_NAMED_ESCAPES = {"\t": r"\t", "\n": r"\n", "\r": r"\r"}


def escape_terminal_line(value: str) -> str:
    return _escape_terminal_controls(value, preserve_layout=False)


def escape_terminal_preview(value: str) -> str:
    return _escape_terminal_controls(value, preserve_layout=True)


def supports_color(stream: TextIO) -> bool:
    if "NO_COLOR" in os.environ or os.environ.get("TERM") == "dumb":
        return False
    try:
        stream.fileno()
    except (AttributeError, OSError, ValueError):
        return False
    return stream.isatty()


def styled(value: str, code: str, *, enabled: bool) -> str:
    value = escape_terminal_line(value)
    if not enabled:
        return value
    return f"\033[{code}m{value}\033[0m"


def _escape_terminal_controls(value: str, *, preserve_layout: bool) -> str:
    escaped: list[str] = []
    for character in value:
        code = ord(character)
        if preserve_layout and character in {"\n", "\t"}:
            escaped.append(character)
        elif code < 0x20 or 0x7F <= code <= 0x9F:
            escaped.append(_NAMED_ESCAPES.get(character, f"\\x{code:02x}"))
        elif 0xDC80 <= code <= 0xDCFF:
            escaped.append(f"\\x{code - 0xDC00:02x}")
        elif 0xD800 <= code <= 0xDFFF:
            escaped.append(f"\\u{code:04x}")
        else:
            escaped.append(character)
    return "".join(escaped)
