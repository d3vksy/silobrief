from __future__ import annotations

import unittest
from importlib.metadata import version
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_README = "examples/parcel-sync-fixture/README.md"
PUBLIC_COMMANDS = (
    "sb setup",
    "sb ignore",
    "sb init",
    "sb log",
    "sb chat",
    "sb --version",
)
README_EXPECTATIONS = {
    "README.md": ("## Exit codes", "not a security scanner"),
    "README.ko.md": ("## 종료 코드", "보안 검사기"),
}
CHANGELOG_EXPECTATIONS = (*PUBLIC_COMMANDS[:-1], "WRITE", "parcel-sync-fixture")
RELEASE_DATE = "2026-08-04"
BRIEF_GUIDANCE_EXPECTATIONS = {
    "README.md": (
        "concrete task",
        "required deliverables",
        "acceptance criteria",
        "approved for external disclosure",
        "private source bodies",
        "secrets",
        "real names from ignored boundaries",
        "does not automatically include source bodies",
    ),
    "README.ko.md": (
        "구체적인 작업",
        "필요한 산출물",
        "인수 기준",
        "외부 공개를 승인",
        "비공개 source body",
        "비밀값",
        "무시한 경계의 실제",
        "source body를 자동으로 포함하지 않습니다",
    ),
}


class ReleaseDocumentationTests(unittest.TestCase):
    def test_readmes_cover_the_public_flow_and_limits(self) -> None:
        for relative_path, specific_fragments in README_EXPECTATIONS.items():
            with self.subTest(path=relative_path):
                text = (REPOSITORY_ROOT / relative_path).read_text(encoding="utf-8")
                for fragment in (*PUBLIC_COMMANDS, FIXTURE_README, "WRITE", *specific_fragments):
                    self.assertIn(fragment, text)
                for exit_code in (0, 2, 3, 4):
                    self.assertIn(f"| `{exit_code}` |", text)

    def test_changelog_covers_the_current_development_scope(self) -> None:
        text = (REPOSITORY_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        for fragment in CHANGELOG_EXPECTATIONS:
            self.assertIn(fragment, text)

    def test_readmes_explain_useful_brief_input(self) -> None:
        for relative_path, fragments in BRIEF_GUIDANCE_EXPECTATIONS.items():
            with self.subTest(path=relative_path):
                text = (REPOSITORY_ROOT / relative_path).read_text(encoding="utf-8")
                for fragment in fragments:
                    self.assertIn(fragment, text)

    def test_v0_1_release_metadata_is_frozen(self) -> None:
        changelog = (REPOSITORY_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        self.assertIn(f"## [Unreleased]\n\n## [0.1.0] - {RELEASE_DATE}", changelog)
        for fragment in ("### Added", "### Fixed", "### Known limitations", "source bodies"):
            self.assertIn(fragment, changelog)

        readme = (REPOSITORY_ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("The current release is v0.1.0.", readme)
        self.assertNotIn("pre-release development", readme)
        readme_ko = (REPOSITORY_ROOT / "README.ko.md").read_text(encoding="utf-8")
        self.assertIn("현재 공개 버전은 v0.1.0입니다.", readme_ko)
        self.assertNotIn("출시 전 개발 단계", readme_ko)

        security = (REPOSITORY_ROOT / "SECURITY.md").read_text(encoding="utf-8")
        self.assertIn("| 0.1.x | :white_check_mark: |", security)
        self.assertNotIn("has not released a supported version yet", security)

        pyproject = (REPOSITORY_ROOT / "pyproject.toml").read_text(encoding="utf-8")
        self.assertEqual(pyproject.count('version = "0.1.0"'), 1)
        self.assertEqual(version("silobrief"), "0.1.0")

    def test_public_fixture_link_points_to_an_existing_file(self) -> None:
        self.assertTrue((REPOSITORY_ROOT / FIXTURE_README).is_file())


if __name__ == "__main__":
    unittest.main()
