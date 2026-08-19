from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import cast

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
VALIDATION_ROOT = REPOSITORY_ROOT / "validation" / "v1.0-scope-related-context"
CORPUS_ROOT = VALIDATION_ROOT / "corpus"
MANIFEST_SHA256 = {
    "v0.4-ranking-holdout": "6fe09278638ccede6e4be981fcc8b2fd5fedcd9288dbcc780210032bce616736",
    "v0.4-edge-idf-holdout": "1b45b645362a26a24e3d89805282b4dfd14c583b527ebe326698fbce4f0b5eaf",
}
FROZEN_EVALUATOR_SHA256 = "124d0e7e68c5a3352a47611ab0ea165a0373b3b832646f956d48035093238d78"
ORACLE_SHA256 = "39a617eab127040f6bfa4a1577dd1be04e4d0f11093ec2c40ffad41427a9b0f1"
RESULT_SHA256 = "0c65bd3a7d64bc5218583b08c332029e384bda63bcd42337999c92ffd0171923"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise AssertionError(f"could not load module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(path.parent))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.pop(0)
    return module


def run_git(
    project: Path,
    *arguments: str,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ("git", *arguments),
        cwd=project,
        check=check,
        capture_output=True,
        text=True,
    )


class ScopeEvaluatorTests(unittest.TestCase):
    def test_frozen_inputs_and_canonical_result_keep_their_hashes(self) -> None:
        cases: list[tuple[str, dict[str, object]]] = []
        for directory, expected_digest in MANIFEST_SHA256.items():
            path = CORPUS_ROOT / directory / "holdout.json"
            self.assertEqual(digest(path), expected_digest)
            value = json.loads(path.read_text(encoding="utf-8"))
            cases.extend((directory, case) for case in value["cases"])

        frozen_evaluator = VALIDATION_ROOT / "frozen_evaluator.py"
        oracle = VALIDATION_ROOT / "oracle.json"
        result = VALIDATION_ROOT / "results.json"
        result_value = json.loads(result.read_text(encoding="utf-8"))

        self.assertEqual(len(cases), 12)
        self.assertEqual(len({str(case["repository"]) for _directory, case in cases}), 12)
        self.assertEqual(digest(frozen_evaluator), FROZEN_EVALUATOR_SHA256)
        self.assertEqual(digest(oracle), ORACLE_SHA256)
        self.assertEqual(digest(result), RESULT_SHA256)
        self.assertEqual(result_value["evaluator_sha256"], FROZEN_EVALUATOR_SHA256)
        self.assertEqual(
            result_value["manifest_sha256"],
            {
                "edge-idf": MANIFEST_SHA256["v0.4-edge-idf-holdout"],
                "ranking": MANIFEST_SHA256["v0.4-ranking-holdout"],
            },
        )

    def test_report_lists_every_pinned_checkout_and_reproduction_command(self) -> None:
        report = (VALIDATION_ROOT / "REPORT.md").read_text(encoding="utf-8")
        for directory in MANIFEST_SHA256:
            value = json.loads((CORPUS_ROOT / directory / "holdout.json").read_text("utf-8"))
            for case in value["cases"]:
                repository = str(case["repository"])
                name = repository.rsplit("/", 1)[-1]
                with self.subTest(repository=repository):
                    self.assertIn(f"https://github.com/{repository}.git", report)
                    self.assertIn(str(case["commit"]), report)
                    self.assertIn(f"corpus/{directory}/repos/{name}", report)
        self.assertIn(
            "python validation/v1.0-scope-related-context/prepare.py",
            report,
        )
        self.assertIn(
            "python validation/v1.0-scope-related-context/evaluate.py --check",
            report,
        )

    def test_missing_inputs_report_paths_and_the_prepare_command(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            external_root = Path(directory) / "empty corpus"
            completed = subprocess.run(
                (
                    sys.executable,
                    str(VALIDATION_ROOT / "evaluate.py"),
                    "--check",
                    "--external-root",
                    str(external_root),
                ),
                cwd=REPOSITORY_ROOT,
                env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertEqual(completed.returncode, 2)
        self.assertEqual(completed.stdout, "")
        self.assertIn(
            str(external_root / "v0.4-ranking-holdout" / "holdout.json"), completed.stderr
        )
        self.assertIn(
            str(external_root / "v0.4-edge-idf-holdout" / "holdout.json"), completed.stderr
        )
        self.assertIn("prepare.py --external-root", completed.stderr)
        self.assertNotIn("FileNotFoundError", completed.stderr)
        self.assertNotIn("Traceback", completed.stderr)

    def test_missing_checkouts_report_paths_and_the_prepare_command(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            external_root = Path(directory) / "manifest-only corpus"
            for name in MANIFEST_SHA256:
                source = CORPUS_ROOT / name / "holdout.json"
                destination = external_root / name / "holdout.json"
                destination.parent.mkdir(parents=True)
                destination.write_bytes(source.read_bytes())
            completed = subprocess.run(
                (
                    sys.executable,
                    str(VALIDATION_ROOT / "evaluate.py"),
                    "--check",
                    "--external-root",
                    str(external_root),
                ),
                cwd=REPOSITORY_ROOT,
                env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertEqual(completed.returncode, 2)
        self.assertIn("pinned scope evaluation checkouts are missing", completed.stderr)
        self.assertIn(
            str(external_root / "v0.4-ranking-holdout" / "repos" / "starlette"),
            completed.stderr,
        )
        self.assertIn("prepare.py --external-root", completed.stderr)
        self.assertNotIn("Traceback", completed.stderr)

    @unittest.skipUnless(sys.platform == "win32", "Windows extended paths only")
    def test_evaluator_uses_extended_windows_paths(self) -> None:
        evaluate_module = load_module("scope_evaluate_windows", VALIDATION_ROOT / "evaluate.py")
        evaluation_root = cast(Callable[[Path], Path], evaluate_module.evaluation_root)

        value = evaluation_root(CORPUS_ROOT.resolve())

        self.assertTrue(str(value).startswith("\\\\?\\"))

    def test_repository_preparation_is_pinned_and_idempotent(self) -> None:
        prepare_module = load_module("scope_prepare_test", VALIDATION_ROOT / "prepare.py")
        prepare_repository = cast(
            Callable[[str, str, Path], str],
            prepare_module.prepare_repository,
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source repository"
            source.mkdir()
            run_git(source, "init", "--quiet", ".")
            (source / "sample.py").write_text("VALUE = 1\n", encoding="utf-8", newline="\n")
            run_git(source, "add", "sample.py")
            run_git(
                source,
                "-c",
                "user.name=Scope Test",
                "-c",
                "user.email=scope@example.invalid",
                "commit",
                "--quiet",
                "-m",
                "fixture",
            )
            commit = run_git(source, "rev-parse", "HEAD").stdout.strip()
            target = root / "prepared" / "repository"
            url = str(source.resolve())

            self.assertEqual(prepare_repository(url, commit, target), "created")
            first_content = (target / "sample.py").read_bytes()
            first_status = run_git(target, "status", "--porcelain=v1").stdout
            self.assertEqual(
                run_git(target, "config", "--get", "core.longpaths").stdout.strip(),
                "true",
            )
            self.assertEqual(prepare_repository(url, commit, target), "reused")

            self.assertEqual(run_git(target, "rev-parse", "HEAD").stdout.strip(), commit)
            self.assertNotEqual(
                run_git(target, "symbolic-ref", "-q", "HEAD", check=False).returncode,
                0,
            )
            self.assertEqual(run_git(target, "status", "--porcelain=v1").stdout, first_status)
            self.assertEqual((target / "sample.py").read_bytes(), first_content)

            (target / "sample.py").write_text("VALUE = 2\n", encoding="utf-8", newline="\n")
            with self.assertRaisesRegex(RuntimeError, "local changes"):
                prepare_repository(url, commit, target)
            self.assertEqual((target / "sample.py").read_text(encoding="utf-8"), "VALUE = 2\n")

    def test_manual_workflow_uses_full_history_and_the_frozen_runtime(self) -> None:
        workflow = (REPOSITORY_ROOT / ".github" / "workflows" / "scope-evaluator.yml").read_text(
            encoding="utf-8"
        )
        for expected in (
            "workflow_dispatch:",
            "fetch-depth: 0",
            'python-version: "3.14.3"',
            "python validation/v1.0-scope-related-context/prepare.py",
            "python validation/v1.0-scope-related-context/evaluate.py --check",
        ):
            self.assertIn(expected, workflow)


if __name__ == "__main__":
    unittest.main()
