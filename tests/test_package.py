from __future__ import annotations

import subprocess
import sys
import tarfile
import tempfile
import unittest
from html.parser import HTMLParser
from importlib.metadata import distribution
from pathlib import Path
from urllib.parse import unquote, urlsplit

import silobrief

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
README_PATHS = (REPOSITORY_ROOT / "README.md", REPOSITORY_ROOT / "README.ko.md")


class _ImageSourceParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.sources: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "img":
            return
        for name, value in attrs:
            if name == "src" and value is not None:
                self.sources.append(value)


def _local_readme_targets() -> set[Path]:
    targets: set[Path] = set()
    for readme_path in README_PATHS:
        text = readme_path.read_text(encoding="utf-8")
        parser = _ImageSourceParser()
        parser.feed(text)
        values = parser.sources
        values.extend(partition.split(")", 1)[0] for partition in text.split("](")[1:])
        for value in values:
            parsed = urlsplit(value)
            if parsed.scheme or parsed.netloc or not parsed.path:
                continue
            target = Path(unquote(parsed.path))
            if target.is_absolute() or ".." in target.parts:
                raise AssertionError(f"README local link leaves the repository: {value}")
            targets.add(target)
    return targets


class PackageMetadataTests(unittest.TestCase):
    def test_distribution_has_only_the_interactive_runtime_dependency(self) -> None:
        requirements = distribution("silobrief").requires or []
        runtime = [requirement for requirement in requirements if "extra ==" not in requirement]

        self.assertEqual(len(runtime), 1, requirements)
        self.assertTrue(runtime[0].startswith("prompt-toolkit<4,>=3.0.52"), runtime)
        self.assertTrue(
            all('extra == "dev"' in item for item in requirements if item not in runtime)
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
        readme_targets = _local_readme_targets()
        missing_repository_targets = {
            path for path in readme_targets if not (REPOSITORY_ROOT / path).is_file()
        }
        self.assertFalse(missing_repository_targets, missing_repository_targets)
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
        required.update(f"{root}/{path.as_posix()}" for path in readme_targets)
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
