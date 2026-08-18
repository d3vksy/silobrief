from __future__ import annotations

import re
import unittest
from importlib.metadata import version
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_README = "examples/parcel-sync-fixture/README.md"
PUBLIC_COMMANDS = (
    "sb setup",
    "sb example",
    "sb ignore",
    "sb unignore",
    "sb init",
    "sb log",
    "sb search",
    "sb language",
    "sb brief",
    "sb chat",
    "sb --version",
)
README_SECTION_EXPECTATIONS = {
    "README.md": (
        "## Quick start",
        "## How it works",
        "## Commands",
        "## Safety and limitations",
        "## Validation status",
        "## Exit codes",
        "## Security",
    ),
    "README.ko.md": (
        "## 빠른 시작",
        "## 작동 방식",
        "## 명령어",
        "## 보호 범위와 한계",
        "## 검증 현황",
        "## 종료 코드",
        "## 보안",
    ),
}
CHANGELOG_EXPECTATIONS = (*PUBLIC_COMMANDS[:-1], "WRITE", "parcel-sync-fixture")
V0_1_RELEASE_DATE = "2026-08-04"
V0_2_RELEASE_DATE = "2026-08-05"
V0_3_RELEASE_DATE = "2026-08-06"
V0_4_RELEASE_DATE = "2026-08-09"
V0_5_RELEASE_DATE = "2026-08-09"
V0_6_RELEASE_DATE = "2026-08-10"
BRIEF_REVIEW_EXPECTATIONS = {
    "README.md": (
        "`PROMPT`",
        "required deliverables",
        "acceptance criteria",
        "`sb log`",
        "EXPOSE",
        "WRITE",
        "included verbatim",
    ),
    "README.ko.md": (
        "`PROMPT`",
        "필요한 결과",
        "완료 조건",
        "`sb log`",
        "EXPOSE",
        "WRITE",
        "원문 그대로 포함",
    ),
}
SAFETY_EXPECTATIONS = {
    "README.md": ("excluded paths", "symbolic links", "not a security scanner"),
    "README.ko.md": ("제외 경로", "심볼릭 링크", "보안 검사기"),
}
VALIDATION_EXPECTATIONS = {
    "README.md": ("v1.0.3", "1.x", "11 of 12", "72.2%"),
    "README.ko.md": ("v1.0.3", "1.x", "12개 과제 중 11개", "72.2%"),
}
VALIDATION_PROJECTS = ("Django Ninja", "pytest", "Jinja")
VALIDATION_LINKS = (
    "validation/v0.2/INSTALLED_WHEEL_VERIFICATION.md",
    "validation/v0.2/MANUAL_MODEL_GATE.md",
    "validation/v0.2/results/CLAUDE_GATE_RESULT.md",
    "validation/v0.7/RETRIEVAL_RESULT.md",
    "validation/v0.8/RELATED_CONTEXT_RESULT.md",
    "validation/v0.9/FIELD_TRIAL.md",
    "validation/v1.0.1/RELEASE_VERIFICATION.md",
)
PRACTICE_FLOW_EXPECTATIONS = (
    "sb example ./silobrief-practice",
    "sb log parcel_practice/labels.py",
    "Append an optional separator to format_label.",
    ".silobrief/exports/task-01-modify.md",
)


class ReleaseDocumentationTests(unittest.TestCase):
    def test_readmes_show_the_repository_wordmark(self) -> None:
        wordmark = ".github/assets/silobrief-wordmark.svg"
        self.assertTrue((REPOSITORY_ROOT / wordmark).is_file())
        wordmark_text = (REPOSITORY_ROOT / wordmark).read_text(encoding="utf-8")
        self.assertIn('viewBox="-100 0 1600 480"', wordmark_text)
        for readme_name in ("README.md", "README.ko.md"):
            with self.subTest(path=readme_name):
                text = (REPOSITORY_ROOT / readme_name).read_text(encoding="utf-8")
                self.assertIn(f'<img src="{wordmark}" alt="siloBrief"', text)

    def test_readme_navigation_links_target_current_sections(self) -> None:
        for readme_name in README_SECTION_EXPECTATIONS:
            with self.subTest(path=readme_name):
                text = (REPOSITORY_ROOT / readme_name).read_text(encoding="utf-8")
                headings = re.findall(r"^##\s+(.+)$", text, flags=re.MULTILINE)
                heading_anchors = {
                    re.sub(r"\s+", "-", re.sub(r"[^\w\s-]", "", heading.lower()).strip())
                    for heading in headings
                }
                navigation_anchors = set(re.findall(r'<a href="#([^"]+)">', text))
                self.assertGreaterEqual(len(navigation_anchors), 6)
                self.assertTrue(navigation_anchors.issubset(heading_anchors))

    def test_readmes_cover_the_public_flow_and_limits(self) -> None:
        for relative_path, sections in README_SECTION_EXPECTATIONS.items():
            with self.subTest(path=relative_path):
                text = (REPOSITORY_ROOT / relative_path).read_text(encoding="utf-8")
                for fragment in (*PUBLIC_COMMANDS, *sections):
                    self.assertIn(fragment, text)
                for exit_code in (0, 2, 3, 4):
                    self.assertIn(f"| `{exit_code}` |", text)

    def test_changelog_covers_the_current_development_scope(self) -> None:
        text = (REPOSITORY_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        for fragment in CHANGELOG_EXPECTATIONS:
            self.assertIn(fragment, text)

    def test_readmes_explain_useful_brief_input(self) -> None:
        for relative_path, fragments in BRIEF_REVIEW_EXPECTATIONS.items():
            with self.subTest(path=relative_path):
                text = (REPOSITORY_ROOT / relative_path).read_text(encoding="utf-8")
                for fragment in fragments:
                    self.assertIn(fragment, text)

    def test_readmes_continue_with_the_generated_practice_project(self) -> None:
        for readme_name in README_SECTION_EXPECTATIONS:
            with self.subTest(path=readme_name):
                text = (REPOSITORY_ROOT / readme_name).read_text(encoding="utf-8")
                for fragment in PRACTICE_FLOW_EXPECTATIONS:
                    self.assertIn(fragment, text)
                self.assertNotIn(FIXTURE_README, text)

    def test_readmes_keep_safety_and_validation_facts(self) -> None:
        for relative_path, safety_fragments in SAFETY_EXPECTATIONS.items():
            with self.subTest(path=relative_path):
                text = (REPOSITORY_ROOT / relative_path).read_text(encoding="utf-8")
                for fragment in (
                    *safety_fragments,
                    *VALIDATION_EXPECTATIONS[relative_path],
                    *VALIDATION_PROJECTS,
                    *VALIDATION_LINKS,
                ):
                    self.assertIn(fragment, text)

    def test_v1_release_metadata_is_current(self) -> None:
        changelog = (REPOSITORY_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        self.assertIn("## [Unreleased]", changelog)
        self.assertIn("## [1.0.3] - 2026-08-18", changelog)
        self.assertIn("## [1.0.2] - 2026-08-17", changelog)
        self.assertIn("## [1.0.1] - 2026-08-12", changelog)
        self.assertIn("## [1.0.0] - 2026-08-11", changelog)
        self.assertIn(f"## [0.6.0] - {V0_6_RELEASE_DATE}", changelog)
        self.assertIn(f"## [0.5.0] - {V0_5_RELEASE_DATE}", changelog)
        self.assertIn(f"## [0.4.0] - {V0_4_RELEASE_DATE}", changelog)
        self.assertIn(f"## [0.3.0] - {V0_3_RELEASE_DATE}", changelog)
        self.assertIn(f"## [0.2.0] - {V0_2_RELEASE_DATE}", changelog)
        self.assertIn(f"## [0.1.0] - {V0_1_RELEASE_DATE}", changelog)
        for fragment in (
            "### Added",
            "### Fixed",
            "### Known limitations",
            "source bodies",
            "excluded src-layout module and symbol names",
        ):
            self.assertIn(fragment, changelog)

        security = (REPOSITORY_ROOT / "SECURITY.md").read_text(encoding="utf-8")
        self.assertIn("| 1.0.x | :white_check_mark: |", security)
        self.assertIn("| 0.6.x | :x: |", security)
        self.assertIn("| 0.5.x | :x: |", security)
        self.assertNotIn("has not released a supported version yet", security)

        pyproject = (REPOSITORY_ROOT / "pyproject.toml").read_text(encoding="utf-8")
        self.assertEqual(pyproject.count('version = "1.0.3"'), 1)
        self.assertEqual(version("silobrief"), "1.0.3")

    def test_public_fixture_link_points_to_an_existing_file(self) -> None:
        self.assertTrue((REPOSITORY_ROOT / FIXTURE_README).is_file())

    def test_pypi_workflow_is_manual_version_checked_and_tokenless(self) -> None:
        workflow = (REPOSITORY_ROOT / ".github" / "workflows" / "publish-pypi.yml").read_text(
            encoding="utf-8"
        )
        for fragment in (
            "workflow_dispatch:",
            "version:",
            "refs/heads/main",
            "refs/tags/v${{ inputs.version }}",
            'project["version"] != version',
            "environment:",
            "name: pypi",
            "id-token: write",
            "pypa/gh-action-pypi-publish@",
            "packages-dir: dist/",
        ):
            self.assertIn(fragment, workflow)
        self.assertNotIn("PYPI_TOKEN", workflow)
        self.assertNotIn("password:", workflow)
        action_references = re.findall(
            r"^\s+uses: ([^\s]+)(?:\s+#.*)?$", workflow, flags=re.MULTILINE
        )
        self.assertTrue(action_references)
        for reference in action_references:
            with self.subTest(reference=reference):
                self.assertRegex(reference, r"^[^@]+@[0-9a-f]{40}$")

        contributing = (REPOSITORY_ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")
        for fragment in (
            "Trusted Publisher",
            "publish-pypi.yml",
            "owner `d3vksy`",
            "environment named `pypi`",
            "without the `v` prefix",
        ):
            self.assertIn(fragment, contributing)


if __name__ == "__main__":
    unittest.main()
