from __future__ import annotations

import contextlib
import io
import unittest
from importlib.metadata import version

from silobrief import __version__
from silobrief.cli import main


class VersionCommandTests(unittest.TestCase):
    def test_version_uses_installed_package_metadata(self) -> None:
        self.assertEqual(__version__, version("silobrief"))

    def test_version_prints_public_product_name(self) -> None:
        stdout = io.StringIO()

        with contextlib.redirect_stdout(stdout), self.assertRaises(SystemExit) as caught:
            main(["--version"])

        self.assertEqual(caught.exception.code, 0)
        self.assertEqual(stdout.getvalue(), "siloBrief 0.1.0\n")
