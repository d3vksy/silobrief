from __future__ import annotations

import contextlib
import io
import unittest
from importlib.metadata import version

from silobrief import __version__
from silobrief.cli import main


class CommandLineTests(unittest.TestCase):
    def test_requires_a_subcommand(self) -> None:
        stderr = io.StringIO()

        with contextlib.redirect_stderr(stderr), self.assertRaises(SystemExit) as caught:
            main([])

        self.assertEqual(caught.exception.code, 2)
        self.assertIn("usage: sb", stderr.getvalue())
        self.assertIn(
            "{setup,example,ignore,unignore,init,log,search,language,brief,chat}",
            stderr.getvalue(),
        )

    def test_help_lists_commands_and_succeeds(self) -> None:
        stdout = io.StringIO()

        with contextlib.redirect_stdout(stdout), self.assertRaises(SystemExit) as caught:
            main(["--help"])

        self.assertEqual(caught.exception.code, 0)
        self.assertIn(
            "{setup,example,ignore,unignore,init,log,search,language,brief,chat}",
            stdout.getvalue(),
        )
        self.assertIn("Deprecated alias for 'brief'", stdout.getvalue())


class VersionCommandTests(unittest.TestCase):
    def test_version_uses_installed_package_metadata(self) -> None:
        self.assertEqual(__version__, version("silobrief"))

    def test_version_prints_public_product_name(self) -> None:
        stdout = io.StringIO()

        with contextlib.redirect_stdout(stdout), self.assertRaises(SystemExit) as caught:
            main(["--version"])

        self.assertEqual(caught.exception.code, 0)
        self.assertEqual(stdout.getvalue(), "siloBrief 1.0.2\n")
