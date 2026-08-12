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
README_EXPECTATIONS = {
    "README.md": ("## Exit codes", "not a security scanner"),
    "README.ko.md": ("## 종료 코드", "보안 검사기"),
}
CHANGELOG_EXPECTATIONS = (*PUBLIC_COMMANDS[:-1], "WRITE", "parcel-sync-fixture")
V0_1_RELEASE_DATE = "2026-08-04"
V0_2_RELEASE_DATE = "2026-08-05"
V0_3_RELEASE_DATE = "2026-08-06"
V0_4_RELEASE_DATE = "2026-08-09"
V0_5_RELEASE_DATE = "2026-08-09"
V0_6_RELEASE_DATE = "2026-08-10"
BRIEF_GUIDANCE_EXPECTATIONS = {
    "README.md": (
        "concrete task",
        "required deliverables",
        "acceptance criteria",
        "approved for external disclosure",
        "private source code",
        "secrets",
        "real names from excluded areas",
        "select and approve",
        "included verbatim",
        "does not detect secrets",
        "EXPOSE",
        "source code you approved",
    ),
    "README.ko.md": (
        "구체적인 작업",
        "필요한 결과",
        "완료 조건",
        "외부 공개를 승인",
        "비공개 소스 코드",
        "비밀값",
        "제외 영역의 실제 이름",
        "선택하고 승인",
        "원문 그대로 포함",
        "비밀정보를 탐지하지",
        "EXPOSE",
        "소스 코드",
    ),
}


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
        readme = (REPOSITORY_ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn('<a href="#security">Security</a>', readme)
        self.assertNotIn('href="#documentation"', readme)

        readme_ko = (REPOSITORY_ROOT / "README.ko.md").read_text(encoding="utf-8")
        self.assertIn('<a href="#보안">보안</a>', readme_ko)
        self.assertNotIn('href="#문서"', readme_ko)

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

    def test_v1_release_metadata_is_current(self) -> None:
        changelog = (REPOSITORY_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        self.assertIn("## [Unreleased]", changelog)
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

        readme = (REPOSITORY_ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("latest public release is v1.0.1", readme)
        self.assertIn("supported 1.x compatibility contract", readme)
        self.assertIn("Create a disposable project", readme)
        self.assertIn("`sb language [", readme)
        self.assertIn("one self-contained Markdown file", readme)
        self.assertIn("Candidate search remains lexical and advisory", readme)
        self.assertIn("exact indexed Python file path", readme)
        self.assertIn("11 of 12 frozen tasks", readme)
        readme_ko = (REPOSITORY_ROOT / "README.ko.md").read_text(encoding="utf-8")
        self.assertIn("최신 공개 버전은 v1.0.1", readme_ko)
        self.assertIn("지원되는 1.x 호환성 계약", readme_ko)
        self.assertIn("버려도 되는 합성 프로젝트", readme_ko)
        self.assertIn("`sb language [", readme_ko)
        self.assertIn("하나의 자족적인 Markdown 파일", readme_ko)
        self.assertIn("색인에 있는 Python 파일의 정확한 상대 경로", readme_ko)
        self.assertIn("고정된 12개 과제 중 11개", readme_ko)

        security = (REPOSITORY_ROOT / "SECURITY.md").read_text(encoding="utf-8")
        self.assertIn("| 1.0.x | :white_check_mark: |", security)
        self.assertIn("| 0.6.x | :x: |", security)
        self.assertIn("| 0.5.x | :x: |", security)
        self.assertNotIn("has not released a supported version yet", security)

        pyproject = (REPOSITORY_ROOT / "pyproject.toml").read_text(encoding="utf-8")
        self.assertEqual(pyproject.count('version = "1.0.1"'), 1)
        self.assertEqual(version("silobrief"), "1.0.1")

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
