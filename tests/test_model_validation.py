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

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = REPOSITORY_ROOT / "examples" / "model-validation-fixture"
PACKET_ROOT = REPOSITORY_ROOT / "validation" / "v0.2" / "packets"
GUIDE = REPOSITORY_ROOT / "validation" / "v0.2" / "MANUAL_MODEL_GATE.md"
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
    source: bytes
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

PACKET_SHA256 = {
    "T01-MODIFY": (
        "0ef829e88a240c29ec62b0281015abec48b6f1b7476ada412059cdfef140dd30",
        "26e81597f2edd4c65f226ddafc4a291e595e5fb75f5a133d5136ca94d106e698",
    ),
    "T02-ADD": (
        "55bee4ae3e5e34f3570c908d88227d8c181b497db916def96669552b6826c744",
        "7deb0e384fbf625f295ade605d6cb1da2d2bc4a9c68ebe83c6fb4e46b4ed6574",
    ),
    "T03-REMOVE": (
        "75fb9d63c0023a3afee3132b2740b308db9ed5cf68cea5087ea890630acb83ce",
        "4ad9d025d2027cc569499a0d42cbdaf6b0b650c5cc6cce09c0bbe74c0aa9c597",
    ),
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
                    main(
                        [
                            "log",
                            "src/parcel_lab/retry.py",
                            "--comment",
                            "urllib3 version is 2.7.0.",
                        ]
                    ),
                )
        if results != (0, 0, 0):
            raise AssertionError(f"fixture preparation failed: {results}")

        before = source_manifest(project)
        generated: list[GeneratedPacket] = []
        for task in TASKS:
            task_root = destination_root / task.id
            task_root.mkdir(parents=True, exist_ok=True)
            main_path = (task_root / f"{task.output_stem}.md").resolve()
            source_path = main_path.with_name(f"{task.output_stem}.sources.md")
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
                    source_path.read_bytes(),
                    (project / ".silobrief" / "index.json").read_bytes(),
                    before,
                    source_manifest(project),
                )
            )
        return tuple(generated)


class ModelValidationTests(unittest.TestCase):
    def test_frozen_packets_match_current_cli_and_preserve_fixture(self) -> None:
        with tempfile.TemporaryDirectory() as first_directory:
            first = generate_packets(Path(first_directory))
        with tempfile.TemporaryDirectory() as second_directory:
            second = generate_packets(Path(second_directory))

        self.assertEqual(first, second)
        for packet in first:
            with self.subTest(task=packet.task.id):
                committed = PACKET_ROOT / packet.task.id
                main = (committed / f"{packet.task.output_stem}.md").read_bytes()
                source = (committed / f"{packet.task.output_stem}.sources.md").read_bytes()
                self.assertEqual(packet.main, main)
                self.assertEqual(packet.source, source)
                self.assertEqual(packet.source_before, packet.source_after)
                self.assertEqual(
                    (
                        hashlib.sha256(main).hexdigest(),
                        hashlib.sha256(source).hexdigest(),
                    ),
                    PACKET_SHA256[packet.task.id],
                )

                combined = packet.index + main + source
                for private in PRIVATE_VALUES:
                    self.assertNotIn(private.encode(), combined)
                for canary in MODULE_CANARIES:
                    self.assertNotIn(canary.encode(), main + source)
                for solution in FORBIDDEN_SOLUTION_SNIPPETS:
                    self.assertNotIn(solution, main + source)

        by_id = {packet.task.id: packet for packet in first}
        self.assertNotIn(b"retry_policy =", by_id["T01-MODIFY"].main)
        self.assertIn(b"retry_policy =", by_id["T01-MODIFY"].source)
        self.assertNotIn(b"class LabelOptions", by_id["T02-ADD"].main)
        self.assertIn(b"class LabelOptions", by_id["T02-ADD"].source)
        self.assertIn(b"def format_label", by_id["T02-ADD"].source)
        self.assertNotIn(b"def choose_reference", by_id["T03-REMOVE"].main)
        self.assertIn(b"def choose_reference", by_id["T03-REMOVE"].source)

    def test_evaluator_guide_freezes_prompts_and_distribution_includes_assets(self) -> None:
        guide = GUIDE.read_text(encoding="utf-8")
        normalized_guide = " ".join(line.removeprefix("> ").strip() for line in guide.splitlines())
        for task in TASKS:
            self.assertIn(task.id, guide)
            self.assertIn(task.prompt, normalized_guide)
            for digest in PACKET_SHA256[task.id]:
                self.assertIn(digest, guide)
        manifest = (REPOSITORY_ROOT / "MANIFEST.in").read_text(encoding="utf-8")
        self.assertIn("examples/model-validation-fixture", manifest)
        self.assertIn("validation/v0.2", manifest)


if __name__ == "__main__":
    unittest.main()
