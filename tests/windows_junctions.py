from __future__ import annotations

import os
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def directory_junction(link: Path, target: Path) -> Iterator[Path]:
    if os.name != "nt":
        raise OSError("directory junctions require Windows")
    result = subprocess.run(
        ["cmd.exe", "/d", "/c", "mklink", "/j", str(link), str(target)],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise OSError("cannot create a directory junction for this test")
    try:
        yield link
    finally:
        try:
            os.rmdir(link)
        except FileNotFoundError:
            pass
