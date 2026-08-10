from __future__ import annotations

import contextlib
import hashlib
import io
import os
import shutil
import sys
import tempfile
import unittest
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from unittest import mock

from silobrief.cli import main
from silobrief.current_index import load_current_index
from silobrief.review import ReviewError, selector_symbol_options

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = REPOSITORY_ROOT / "examples" / "model-validation-fixture"
GUIDE = REPOSITORY_ROOT / "validation" / "v0.2" / "MANUAL_MODEL_GATE.md"
VERIFICATION = REPOSITORY_ROOT / "validation" / "v0.2" / "INSTALLED_WHEEL_VERIFICATION.md"
CLAUDE_RESULT = REPOSITORY_ROOT / "validation" / "v0.2" / "results" / "CLAUDE_GATE_RESULT.md"
MODEL_MESSAGE = "첨부한 main brief의 지시를 수행하세요."
PRIVATE_VALUES = ("PRIVATE_MODEL_GATE_CANARY", "ignored-adapter-source", "private_adapter")
MODULE_CANARIES = (
    "VALIDATION_MODULE_CANARY_RETRY",
    "VALIDATION_MODULE_CANARY_LABELS",
    "VALIDATION_MODULE_CANARY_CLEANUP",
)
FORBIDDEN_SOLUTION_SNIPPETS = (
    b"status_forcelist=[503]",
    b"status_forcelist = [503]",
    b"separator: str =",
    b"def choose_reference(primary: str) -> str",
)


@dataclass(frozen=True, slots=True)
class Task:
    id: str
    output_stem: str
    prompt: str
    review_input: str


@dataclass(frozen=True, slots=True)
class GeneratedPacket:
    task: Task
    main: bytes
    index: bytes
    source_before: tuple[tuple[str, str], ...]
    source_after: tuple[tuple[str, str], ...]


TASKS = (
    Task(
        "T01-MODIFY",
        "t01-modify",
        "Update the retry policy in src/parcel_lab/retry.py so status-code retries apply to "
        "HTTP 503 and not HTTP 500. Keep total=2 and preserve the delivery boundary call order. "
        "Return a minimal patch and focused unittest. Do not claim you ran tests.",
        "y\n2\n\n\ny\ny\ny\ny\ny\ny\nEXPOSE\nWRITE\n",
    ),
    Task(
        "T02-ADD",
        "t02-add",
        "Add an optional separator: str setting to LabelOptions. Existing callers that omit it "
        "must keep current output. When both prefix and separator are non-empty, place the "
        "separator between prefix and reference. Preserve uppercase behavior. Return a minimal "
        "patch and focused unittests.",
        "y\n1 2\n\n\ny\ny\ny\ny\ny\ny\ny\nWRITE\n",
    ),
    Task(
        "T03-REMOVE",
        "t03-remove",
        "Remove the legacy fallback from choose_reference. The function must accept only primary, "
        "return its stripped value, and raise ValueError when it is blank. Return a minimal patch "
        "and focused unittests. State the interface impact without inventing call sites.",
        "y\n1\n\n\ny\ny\ny\ny\ny\ny\nWRITE\n",
    ),
)

LEGACY_PACKET_SHA256 = {
    "T01-MODIFY": (
        "799c083b0df08b8a62af1d6e0078fded210757acd288d8872b918136d7fed4c3",
        "26e81597f2edd4c65f226ddafc4a291e595e5fb75f5a133d5136ca94d106e698",
    ),
    "T02-ADD": (
        "1a4047204b5d474acad6572cb15c906aea1295242bdeaa10cc8abe46793da11b",
        "7deb0e384fbf625f295ade605d6cb1da2d2bc4a9c68ebe83c6fb4e46b4ed6574",
    ),
    "T03-REMOVE": (
        "de1df5fd18c72840f401229e7fc6f25016ecfaa70ac5bd643ecf59c22fee8311",
        "4ad9d025d2027cc569499a0d42cbdaf6b0b650c5cc6cce09c0bbe74c0aa9c597",
    ),
}

COMBINED_PACKET_SHA256 = {
    "T01-MODIFY": "d43382535342ce442f4c88e8fb27c33578f72db486f9c2081e2d5c863f225115",
    "T02-ADD": "3d1c61aa0c274ee3a5d149a11def4458f11381fc714606775204e015666bd8b5",
    "T03-REMOVE": "1aa3dc9ff544ddca94787a8f8d5e8d0cab559935c77b5e6bf0e56b820a57531d",
}

CLAUDE_RESPONSE_SHA256 = {
    "T01-MODIFY.md": "ee4b72b598fec70b1d6f552c38b31d4a374ddeea8ad4fbed6dea87083b014936",
    "T02-ADD.md": "a261bfc694ca8ef43daf2d3dce21aa4aa2fc51844e6e2eee90a8702f1d269807",
    "T03-REMOVE.md": "d7e32f7309c985c3cd92f743fb0a1bf213d55df9f4c8c684e2f578f4f18c6ab2",
}


class TtyBuffer(io.StringIO):
    def isatty(self) -> bool:
        return True


@contextlib.contextmanager
def working_directory(path: Path) -> Iterator[None]:
    previous = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous)


def source_manifest(project: Path) -> tuple[tuple[str, str], ...]:
    return tuple(
        (path.relative_to(project).as_posix(), hashlib.sha256(path.read_bytes()).hexdigest())
        for path in sorted(project.rglob("*"))
        if path.is_file() and ".silobrief" not in path.parts
    )


def generate_packets(destination_root: Path) -> tuple[GeneratedPacket, ...]:
    with tempfile.TemporaryDirectory() as directory:
        project = Path(directory) / "fixture"
        shutil.copytree(FIXTURE_ROOT, project)
        terminal = TtyBuffer()
        with contextlib.redirect_stdout(terminal), contextlib.redirect_stderr(terminal):
            if main(["setup", str(project)]) != 0:
                raise AssertionError("fixture setup failed")
            with working_directory(project):
                results = (
                    main(
                        [
                            "ignore",
                            "private_adapter",
                            "--as",
                            "External delivery adapter",
                            "--alias",
                            "delivery-boundary",
                        ]
                    ),
                    main(["init"]),
                    main(["language", "--brief", "ko"]),
                    main(
                        [
                            "log",
                            "src/parcel_lab/retry.py",
                            "--comment",
                            "urllib3 version is 2.7.0.",
                        ]
                    ),
                )
        if results != (0, 0, 0, 0):
            raise AssertionError(f"fixture preparation failed: {results}")

        before = source_manifest(project)
        generated: list[GeneratedPacket] = []
        for task in TASKS:
            task_root = destination_root / task.id
            task_root.mkdir(parents=True, exist_ok=True)
            main_path = (task_root / f"{task.output_stem}.md").resolve()
            stdin = TtyBuffer(task.review_input)
            stdout = TtyBuffer()
            stderr = io.StringIO()
            with (
                working_directory(project),
                mock.patch.object(sys, "stdin", stdin),
                contextlib.redirect_stdout(stdout),
                contextlib.redirect_stderr(stderr),
                mock.patch(
                    "socket.create_connection",
                    side_effect=AssertionError("network access is forbidden"),
                ),
                mock.patch(
                    "socket.socket.connect",
                    side_effect=AssertionError("network access is forbidden"),
                ),
            ):
                result = main(["chat", task.prompt, "--out", str(main_path)])
            if result != 0 or stderr.getvalue():
                raise AssertionError(f"{task.id} generation failed: {stderr.getvalue()}")
            generated.append(
                GeneratedPacket(
                    task,
                    main_path.read_bytes(),
                    (project / ".silobrief" / "index.json").read_bytes(),
                    before,
                    source_manifest(project),
                )
            )
        return tuple(generated)


class ModelValidationTests(unittest.TestCase):
    def test_guided_outline_cannot_select_a_symlinked_source(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project"
            project.mkdir()
            outside = root / "outside.py"
            outside.write_text(
                "SYMLINK_GUIDED_CANARY = True\n\ndef outside_function():\n    return None\n",
                encoding="utf-8",
                newline="\n",
            )
            linked = project / "linked.py"
            try:
                linked.symlink_to(outside)
            except OSError as error:
                self.skipTest(f"symbolic links unavailable: {error}")

            terminal = TtyBuffer()
            with contextlib.redirect_stdout(terminal), contextlib.redirect_stderr(terminal):
                self.assertEqual(main(["setup", str(project)]), 0)
                with working_directory(project):
                    self.assertEqual(main(["init"]), 0)
            index, _ = load_current_index(project)

        self.assertNotIn("SYMLINK_GUIDED_CANARY", repr(index))
        with self.assertRaisesRegex(ReviewError, "not present in the current index"):
            selector_symbol_options(index, "linked.py")

    def test_guided_outline_covers_the_three_frozen_task_files(self) -> None:
        expected = {
            "src/parcel_lab/retry.py": (("function", "retry_request"),),
            "src/parcel_lab/labels.py": (
                ("class", "LabelOptions"),
                ("function", "format_label"),
            ),
            "src/parcel_lab/cleanup.py": (("function", "choose_reference"),),
        }
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "fixture"
            shutil.copytree(FIXTURE_ROOT, project)
            terminal = TtyBuffer()
            with contextlib.redirect_stdout(terminal), contextlib.redirect_stderr(terminal):
                self.assertEqual(main(["setup", str(project)]), 0)
                with working_directory(project):
                    self.assertEqual(
                        main(
                            [
                                "ignore",
                                "private_adapter",
                                "--as",
                                "External delivery adapter",
                                "--alias",
                                "delivery-boundary",
                            ]
                        ),
                        0,
                    )
                    self.assertEqual(main(["init"]), 0)
            index, _ = load_current_index(project)

        for path, symbols in expected.items():
            with self.subTest(path=path):
                options = selector_symbol_options(index, path)
                self.assertIsNotNone(options)
                self.assertEqual(
                    tuple(
                        (option.node.kind, option.node.qualified_name) for option in options or ()
                    ),
                    symbols,
                )
        with self.assertRaisesRegex(ReviewError, "not present in the current index"):
            selector_symbol_options(index, "private_adapter/client.py")

    def test_combined_packets_are_deterministic_and_preserve_fixture(self) -> None:
        with tempfile.TemporaryDirectory() as first_directory:
            first = generate_packets(Path(first_directory))
        with tempfile.TemporaryDirectory() as second_directory:
            second = generate_packets(Path(second_directory))

        self.assertEqual(first, second)
        for packet in first:
            with self.subTest(task=packet.task.id):
                self.assertEqual(packet.source_before, packet.source_after)
                self.assertEqual(
                    hashlib.sha256(packet.main).hexdigest(),
                    COMBINED_PACKET_SHA256[packet.task.id],
                )

                combined = packet.index + packet.main
                for private in PRIVATE_VALUES:
                    self.assertNotIn(private.encode(), combined)
                for canary in MODULE_CANARIES:
                    self.assertNotIn(canary.encode(), packet.main)
                for solution in FORBIDDEN_SOLUTION_SNIPPETS:
                    self.assertNotIn(solution, packet.main)
                for requirement in (
                    "## 패치".encode(),
                    "`diff` 코드 블록".encode(),
                    b"`-`",
                    b"`+`",
                    b"source_delivery: embedded",
                ):
                    self.assertIn(requirement, packet.main)
                for removed_requirement in (
                    b"unified diff",
                    b"--- a/",
                    b"+++ b/",
                    b"/dev/null",
                ):
                    self.assertNotIn(removed_requirement, packet.main)
                self.assertNotIn("패치 또는 교체 코드".encode(), packet.main)

        by_id = {packet.task.id: packet for packet in first}
        self.assertIn(b"retry_policy =", by_id["T01-MODIFY"].main)
        self.assertIn(b"class LabelOptions", by_id["T02-ADD"].main)
        self.assertIn(b"def format_label", by_id["T02-ADD"].main)
        self.assertIn(b"def choose_reference", by_id["T03-REMOVE"].main)

    def test_evaluator_guide_freezes_prompts_and_distribution_includes_assets(self) -> None:
        guide = GUIDE.read_text(encoding="utf-8")
        normalized_guide = " ".join(line.removeprefix("> ").strip() for line in guide.splitlines())
        self.assertIn(MODEL_MESSAGE, guide)
        for task in TASKS:
            self.assertIn(task.id, guide)
            self.assertIn(task.prompt, normalized_guide)
            for digest in LEGACY_PACKET_SHA256[task.id]:
                self.assertIn(digest, guide)
        manifest = (REPOSITORY_ROOT / "MANIFEST.in").read_text(encoding="utf-8")
        self.assertIn("examples/model-validation-fixture", manifest)
        self.assertIn("validation/v0.2", manifest)

    def test_claude_gate_result_records_limited_release_decision(self) -> None:
        result = CLAUDE_RESULT.read_text(encoding="utf-8")
        self.assertIn("CLAUDE-GATE-PASS (3/3)", result)
        self.assertIn("exact Claude model name and mode were not recorded", result)
        self.assertIn("GPT was not run", result)
        self.assertIn("does not establish cross-model effectiveness", result)

        raw_root = CLAUDE_RESULT.parent / "claude"
        for filename, expected in CLAUDE_RESPONSE_SHA256.items():
            with self.subTest(filename=filename):
                actual = hashlib.sha256((raw_root / filename).read_bytes()).hexdigest()
                self.assertEqual(actual, expected)
                self.assertIn(expected, result)

    def test_installed_wheel_verification_records_release_candidate(self) -> None:
        verification = VERIFICATION.read_text(encoding="utf-8")
        self.assertIn("PASS FOR v0.2.0 RELEASE CANDIDATE", verification)
        self.assertIn("84747f3d2be6243f56a09d94998cdd1c54fbdc4b", verification)
        self.assertIn("silobrief-0.2.0-py3-none-any.whl", verification)
        self.assertIn(
            "0d74eaabe402c2f6d00a85bca590017d91b3e4899c1d31daa247ed86c1485de5",
            verification,
        )
        self.assertIn("30967246484", verification)
        self.assertIn("GPT validation is deferred", verification)


if __name__ == "__main__":
    unittest.main()
