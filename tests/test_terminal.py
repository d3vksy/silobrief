from __future__ import annotations

import io
import os
import unittest
from unittest import mock

from silobrief.terminal import (
    escape_terminal_line,
    escape_terminal_preview,
    styled,
    supports_color,
)


def _is_terminal_control(value: str) -> bool:
    code = ord(value)
    return code < 0x20 or 0x7F <= code <= 0x9F


class ColorTty(io.StringIO):
    def fileno(self) -> int:
        return 1

    def isatty(self) -> bool:
        return True


class TerminalTests(unittest.TestCase):
    def test_escapes_every_c0_c1_and_delete_control(self) -> None:
        controls = "".join(chr(code) for code in (*range(0x20), 0x7F, *range(0x80, 0xA0)))

        single_line = escape_terminal_line(controls)
        preview = escape_terminal_preview(controls)

        self.assertFalse(any(_is_terminal_control(character) for character in single_line))
        self.assertFalse(
            any(
                _is_terminal_control(character) and character not in {"\n", "\t"}
                for character in preview
            )
        )
        self.assertEqual(
            {character for character in preview if _is_terminal_control(character)}, {"\n", "\t"}
        )

    def test_escapes_terminal_controls_in_single_line_values(self) -> None:
        value = "한글\tline\r\nosc\x1b]52;c;Y2xpcGJvYXJk\x07 csi\x1b[2J c1\x9b31m del\x7f nul\x00"

        escaped = escape_terminal_line(value)

        self.assertEqual(
            escaped,
            "한글\\tline\\r\\n"
            "osc\\x1b]52;c;Y2xpcGJvYXJk\\x07"
            " csi\\x1b[2J c1\\x9b31m del\\x7f nul\\x00",
        )
        self.assertFalse(any(_is_terminal_control(character) for character in escaped))

    def test_preview_keeps_newlines_tabs_and_unicode_only(self) -> None:
        value = "한글\tlayout\nnext\r\x1b[H\x85\x7f"

        escaped = escape_terminal_preview(value)

        self.assertEqual(escaped, "한글\tlayout\nnext\\r\\x1b[H\\x85\\x7f")
        self.assertFalse(
            any(
                _is_terminal_control(character) and character not in {"\n", "\t"}
                for character in escaped
            )
        )

    def test_style_wraps_only_the_sanitized_value(self) -> None:
        attack = "value\x1b[31mforged\x1b[0m"

        plain = styled(attack, "1;33", enabled=False)
        colored = styled(attack, "1;33", enabled=True)

        self.assertEqual(plain, "value\\x1b[31mforged\\x1b[0m")
        self.assertEqual(colored, "\x1b[1;33mvalue\\x1b[31mforged\\x1b[0m\x1b[0m")
        self.assertNotIn(attack, plain)
        self.assertNotIn(attack, colored)

    def test_escapes_posix_surrogateescaped_control_bytes(self) -> None:
        value = "path-\udc9b2J-\udc9d52;c;data\udc9c-\udcff-\ud800"

        escaped = escape_terminal_line(value)

        self.assertEqual(escaped, "path-\\x9b2J-\\x9d52;c;data\\x9c-\\xff-\\ud800")
        self.assertEqual(
            escaped.encode("utf-8", errors="surrogateescape"),
            b"path-\\x9b2J-\\x9d52;c;data\\x9c-\\xff-\\ud800",
        )

    def test_uses_ansi_styles_only_for_an_interactive_terminal(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertTrue(supports_color(ColorTty()))
            self.assertFalse(supports_color(io.StringIO()))
            self.assertEqual(styled("value", "1;33", enabled=True), "\033[1;33mvalue\033[0m")
            self.assertEqual(styled("value", "1;33", enabled=False), "value")

    def test_no_color_environment_variable_disables_styles(self) -> None:
        with mock.patch.dict(os.environ, {"NO_COLOR": "1"}, clear=True):
            self.assertFalse(supports_color(ColorTty()))


if __name__ == "__main__":
    unittest.main()
