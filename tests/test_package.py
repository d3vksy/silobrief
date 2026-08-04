from __future__ import annotations

import subprocess
import sys
import tarfile
import tempfile
import unittest
from importlib.metadata import distribution
from pathlib import Path

import silobrief

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


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


class SourceDistributionTests(unittest.TestCase):
    def test_sdist_contains_public_documentation_and_fixture(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "build",
                    "--sdist",
                    "--no-isolation",
                    "--outdir",
                    directory,
                    str(REPOSITORY_ROOT),
                ],
                cwd=directory,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            archives = tuple(Path(directory).glob("*.tar.gz"))
            self.assertEqual(len(archives), 1, archives)
            with tarfile.open(archives[0], mode="r:gz") as archive:
                members = set(archive.getnames())

        root = f"silobrief-{distribution('silobrief').version}"
        required = {
            f"{root}/CHANGELOG.md",
            f"{root}/CODE_OF_CONDUCT.md",
            f"{root}/CONTRIBUTING.md",
            f"{root}/README.ko.md",
            f"{root}/SECURITY.md",
            f"{root}/docs/V0_1_CONTRACT.md",
            f"{root}/examples/parcel-sync-fixture/README.md",
            f"{root}/examples/parcel-sync-fixture/private_adapter/client.py",
            f"{root}/examples/parcel-sync-fixture/src/parcel_sync/service.py",
        }
        self.assertFalse(required - members, required - members)
