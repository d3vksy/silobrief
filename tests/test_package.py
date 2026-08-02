from __future__ import annotations

import unittest
from importlib.metadata import distribution
from pathlib import Path

import silobrief


class PackageMetadataTests(unittest.TestCase):
    def test_distribution_has_no_runtime_dependencies(self) -> None:
        requirements = distribution("silobrief").requires or []

        self.assertTrue(
            all('extra == "dev"' in requirement for requirement in requirements),
            requirements,
        )

    def test_distribution_includes_typing_marker(self) -> None:
        package_file = silobrief.__file__
        assert package_file is not None

        self.assertTrue(Path(package_file).with_name("py.typed").is_file())
