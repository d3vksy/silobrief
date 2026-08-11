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
    def test_sdist_contains_public_assets_and_excludes_internal_artifacts(self) -> None:
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
            f"{root}/.github/workflows/publish-pypi.yml",
            f"{root}/CHANGELOG.md",
            f"{root}/CODE_OF_CONDUCT.md",
            f"{root}/CONTRIBUTING.md",
            f"{root}/README.ko.md",
            f"{root}/SECURITY.md",
            f"{root}/tests/__init__.py",
            f"{root}/examples/parcel-sync-fixture/README.md",
            f"{root}/examples/parcel-sync-fixture/private_adapter/client.py",
            f"{root}/examples/parcel-sync-fixture/src/parcel_sync/service.py",
            f"{root}/validation/v0.7/RETRIEVAL_RESULT.md",
            f"{root}/validation/v0.8/RELATED_CONTEXT_RESULT.md",
            f"{root}/validation/v0.9/FIELD_TRIAL.md",
            f"{root}/validation/v1.0/RELEASE_CANDIDATE.md",
        }
        forbidden = {
            f"{root}/validation/graph-retrieval/BASELINE.md",
            f"{root}/validation/graph-retrieval/COMPARISON.md",
            f"{root}/validation/graph_retrieval_comparison.py",
        }
        self.assertFalse(required - members, required - members)
        self.assertFalse(forbidden & members, forbidden & members)
        self.assertFalse(
            any(member.startswith(f"{root}/docs/") for member in members),
            "sdist must not contain the removed docs tree",
        )
