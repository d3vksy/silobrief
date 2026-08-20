from __future__ import annotations

import os
import subprocess
import sys
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


@contextmanager
def substituted_drive(target: Path) -> Iterator[Path]:
    if os.name != "nt":
        raise OSError("substituted drives require Windows")
    drive: str | None = None
    for letter in "ZYXWVUTSRQP":
        candidate = f"{letter}:"
        result = subprocess.run(
            ["subst", candidate, str(target.resolve(strict=True))],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            drive = candidate
            break
    if drive is None:
        raise OSError("cannot reserve a substituted drive for this test")
    try:
        yield Path(f"{drive}\\")
    finally:
        subprocess.run(["subst", drive, "/D"], check=True, capture_output=True, text=True)


def short_windows_path(path: Path) -> Path:
    if sys.platform != "win32":
        raise OSError("short paths require Windows")
    import ctypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    get_short_path = kernel32.GetShortPathNameW
    get_short_path.argtypes = (ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint32)
    get_short_path.restype = ctypes.c_uint32
    buffer = ctypes.create_unicode_buffer(32768)
    length = get_short_path(str(path), buffer, len(buffer))
    if length == 0 or length >= len(buffer):
        raise OSError(ctypes.get_last_error(), "cannot resolve a short Windows path")
    return Path(buffer.value)
