from __future__ import annotations

import io
import os
import unittest
from unittest import mock

from silobrief.terminal import styled, supports_color


class ColorTty(io.StringIO):
    def fileno(self) -> int:
        return 1

    def isatty(self) -> bool:
        return True


class TerminalTests(unittest.TestCase):
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
