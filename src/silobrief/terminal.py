from __future__ import annotations

import os
from typing import TextIO


def supports_color(stream: TextIO) -> bool:
    if "NO_COLOR" in os.environ or os.environ.get("TERM") == "dumb":
        return False
    try:
        stream.fileno()
    except (AttributeError, OSError, ValueError):
        return False
    return stream.isatty()


def styled(value: str, code: str, *, enabled: bool) -> str:
    if not enabled:
        return value
    return f"\033[{code}m{value}\033[0m"
