from __future__ import annotations

import os
import stat
from pathlib import Path

_REPARSE_POINT = int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))


def is_link_like(path: Path) -> bool:
    try:
        return is_link_like_stat(path.stat(follow_symlinks=False))
    except OSError:
        return False


def is_link_like_stat(metadata: os.stat_result) -> bool:
    attributes = int(getattr(metadata, "st_file_attributes", 0))
    return stat.S_ISLNK(metadata.st_mode) or bool(attributes & _REPARSE_POINT)


def has_link_like_component(path: Path) -> bool:
    absolute = path.absolute()
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current /= part
        if is_link_like(current):
            return True
    return False
