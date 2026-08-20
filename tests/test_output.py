from __future__ import annotations

import errno
import io
import os
import tempfile
import unittest
from collections.abc import Callable
from contextlib import ExitStack
from dataclasses import replace
from pathlib import Path
from typing import TextIO, cast
from unittest import mock

from silobrief import output as output_module
from silobrief import sources as sources_module
from silobrief.boundaries import register_boundary
from silobrief.current_index import (
    CurrentIndexApproval,
    CurrentIndexError,
    load_current_index_for_approval,
)
from silobrief.initialization import initialize_index
from silobrief.output import (
    OutputBlockedError,
    WrittenBrief,
    _uses_foreign_windows_path,
    approve_and_write,
)
from silobrief.renderer import BriefInput, RenderedBrief, render_brief
from silobrief.source_review import ApprovedSourceExcerpt
from silobrief.sources import (
    SourceRootIdentity,
    SourceSnapshot,
    load_source_config,
    snapshot_sources,
)
from silobrief.state import ConfigData, SetupError, load_config, mark_index_stale, setup_project
from tests.windows_junctions import directory_junction


class TtyBuffer(io.StringIO):
    def __init__(self, value: str = "", *, tty: bool = True) -> None:
        super().__init__(value)
        self.tty = tty
        self.flush_count = 0

    def isatty(self) -> bool:
        return self.tty

    def flush(self) -> None:
        self.flush_count += 1
        super().flush()


class RacingInput:
    def __init__(self, target: Path) -> None:
        self.target = target

    def isatty(self) -> bool:
        return True

    def readline(self, size: int = -1) -> str:
        self.target.write_text("rival content", encoding="utf-8")
        return "WRITE\n" if size != 0 else ""


class SourceChangingInput:
    def __init__(self, source: Path) -> None:
        self.source = source

    def isatty(self) -> bool:
        return True

    def readline(self, size: int = -1) -> str:
        self.source.write_text("VALUE = 2\n", encoding="utf-8")
        return "WRITE\n" if size != 0 else ""


class PolicyChangingInput:
    def __init__(self, callback: Callable[[], None]) -> None:
        self.stream = io.StringIO("WRITE\n")
        self.callback = callback

    def isatty(self) -> bool:
        return True

    def readline(self, size: int = -1) -> str:
        self.callback()
        return self.stream.readline(size)


class ParentReplacingInput:
    def __init__(
        self,
        parent: Path,
        backup: Path,
        outside: Path,
        junctions: ExitStack,
    ) -> None:
        self.parent = parent
        self.backup = backup
        self.outside = outside
        self.junctions = junctions
        self.swap_blocked = False
        self.swapped = False

    def isatty(self) -> bool:
        return True

    def readline(self, size: int = -1) -> str:
        try:
            self.parent.rename(self.backup)
        except OSError:
            self.swap_blocked = True
        else:
            self.swapped = True
            self.junctions.enter_context(directory_junction(self.parent, self.outside))
        return "WRITE\n" if size != 0 else ""


class RealDirectoryReplacingInput:
    def __init__(self, parent: Path, backup: Path, replacement: Path) -> None:
        self.parent = parent
        self.backup = backup
        self.replacement = replacement

    def isatty(self) -> bool:
        return True

    def readline(self, size: int = -1) -> str:
        self.parent.rename(self.backup)
        self.replacement.rename(self.parent)
        return "WRITE\n" if size != 0 else ""


class SnapshotThenReplace:
    def __init__(self, target: Path, backup: Path, replacement: Path) -> None:
        self.target = target
        self.backup = backup
        self.replacement = replacement
        self.snapshot = output_module._snapshot
        self.calls = 0
        self.blocked = False
        self.swapped = False

    def __call__(
        self,
        root: Path,
        *,
        expected_root_identity: SourceRootIdentity | None = None,
    ) -> SourceSnapshot:
        snapshot = self.snapshot(root, expected_root_identity=expected_root_identity)
        self.calls += 1
        if self.calls == 1:
            try:
                self.target.rename(self.backup)
            except OSError:
                self.blocked = True
            else:
                self.replacement.rename(self.target)
                self.swapped = True
        return snapshot


class PublishThenReplace:
    def __init__(
        self,
        target: Path,
        backup: Path,
        replacement: Path,
        *,
        final_parent: bool,
        use_symlink: bool,
    ) -> None:
        self.target = target
        self.backup = backup
        self.replacement = replacement
        self.final_parent = final_parent
        self.use_symlink = use_symlink
        self.publish = output_module._publish_created_file

    def __call__(
        self,
        created: output_module._CreatedFile,
        *,
        directory_descriptor: int | None,
    ) -> None:
        self.publish(created, directory_descriptor=directory_descriptor)
        self.target.rename(self.backup)
        if self.use_symlink:
            self.target.symlink_to(self.replacement, target_is_directory=True)
        else:
            self.replacement.rename(self.target)
        current_parent = self.target if self.final_parent else self.target / "nested"
        (current_parent / "result.md").write_text("rival content", encoding="utf-8")


class AbaSwap:
    def __init__(self, target: Path, replacement: Path) -> None:
        self.target = target
        self.replacement = replacement
        self.backup = target.with_name(f"{target.name}-approval-backup")
        self.blocked = False
        self.swapped = False

    def __call__(self) -> None:
        try:
            self.target.rename(self.backup)
        except OSError:
            self.blocked = True
            return
        try:
            self.replacement.rename(self.target)
            self.target.rename(self.replacement)
            self.backup.rename(self.target)
            self.swapped = True
        finally:
            if self.backup.exists():
                if self.target.exists() and not self.replacement.exists():
                    self.target.rename(self.replacement)
                if not self.target.exists():
                    self.backup.rename(self.target)


class WriteThenAba:
    def __init__(self, write: Callable[[int, bytes], None], attack: AbaSwap) -> None:
        self.write = write
        self.attack = attack

    def __call__(self, descriptor: int, content: bytes) -> None:
        self.write(descriptor, content)
        self.attack()


class PublishThenAba:
    def __init__(self, publish: Callable[..., None], attack: AbaSwap) -> None:
        self.publish = publish
        self.attack = attack

    def __call__(
        self,
        created: output_module._CreatedFile,
        *,
        directory_descriptor: int | None,
    ) -> None:
        self.publish(created, directory_descriptor=directory_descriptor)
        self.attack()


def descriptor_count() -> int | None:
    descriptors = Path("/proc/self/fd")
    return len(tuple(descriptors.iterdir())) if descriptors.is_dir() else None


def write_external_output(
    project: Path,
    destination: Path,
    snapshot: SourceSnapshot,
    approval_state: CurrentIndexApproval,
) -> WrittenBrief:
    return approve_and_write(
        project,
        str(destination),
        rendered_source_brief(),
        start=project,
        source_snapshot=snapshot,
        approval_state=approval_state,
        input_stream=TtyBuffer("WRITE\n"),
        output_stream=TtyBuffer(),
    )


def rendered_brief() -> RenderedBrief:
    return render_brief(
        BriefInput(
            user_prompt="공식 문서를 확인해줘",
            relative_paths=("src/api.py",),
            symbols=(),
            public_imports=("Python",),
            human_notes=(),
            boundaries=(),
            source_excerpts=(),
        )
    )


def rendered_source_brief() -> RenderedBrief:
    excerpt = ApprovedSourceExcerpt(
        path="src/api.py",
        kind="function",
        qualified_name="run",
        start_line=1,
        end_line=2,
        content="def run():\n    return 1\n",
        boundary_aliases=(),
    )
    return render_brief(
        BriefInput(
            user_prompt="코드를 수정해줘",
            relative_paths=("src/api.py",),
            symbols=(),
            public_imports=(),
            human_notes=(),
            boundaries=(),
            source_excerpts=(excerpt,),
        )
    )


def project_in(directory: str) -> Path:
    project = Path(directory) / "project"
    project.mkdir()
    setup_project(project)
    return project


class ApprovedOutputTests(unittest.TestCase):
    def test_distinguishes_posix_absolute_paths_from_windows_syntax(self) -> None:
        self.assertFalse(_uses_foreign_windows_path("/tmp/brief.md", platform="posix"))
        self.assertTrue(_uses_foreign_windows_path("C:\\temp\\brief.md", platform="posix"))
        self.assertTrue(_uses_foreign_windows_path("\\temp\\brief.md", platform="posix"))
        self.assertFalse(_uses_foreign_windows_path("C:\\temp\\brief.md", platform="nt"))

    def test_previews_full_markdown_and_writes_new_utf8_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = project_in(directory)
            rendered = rendered_brief()
            stdin = TtyBuffer("WRITE\n")
            stdout = TtyBuffer()

            result = approve_and_write(
                project,
                ".silobrief/exports/result.md",
                rendered,
                start=project,
                input_stream=stdin,
                output_stream=stdout,
            )

            destination = project / ".silobrief" / "exports" / "result.md"
            self.assertEqual(result, WrittenBrief(destination.resolve()))
            self.assertEqual(destination.read_bytes(), rendered.markdown.encode("utf-8"))
            self.assertTrue(stdout.getvalue().startswith(rendered.markdown))
            self.assertIn("exactly WRITE", stdout.getvalue())
            self.assertGreaterEqual(stdout.flush_count, 1)
            self.assertEqual([path.name for path in destination.parent.iterdir()], ["result.md"])

    def test_terminal_preview_escapes_controls_but_saved_markdown_is_verbatim(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = project_in(directory)
            osc = "\x1b]52;c;Y2xpcGJvYXJk\x07"
            markdown = f"# 한글\n\tclipboard {osc}\nclear \x1b[2J c1 \x9b31m del \x7f\r\n"
            rendered = RenderedBrief(markdown, rendered_brief().disclosure)
            stdout = TtyBuffer()

            approve_and_write(
                project,
                ".silobrief/exports/controls.md",
                rendered,
                start=project,
                input_stream=TtyBuffer("WRITE\n"),
                output_stream=stdout,
            )

            destination = project / ".silobrief" / "exports" / "controls.md"
            visible = stdout.getvalue()
            self.assertNotIn(osc, visible)
            self.assertNotIn("\x1b[2J", visible)
            self.assertIn("# 한글\n\tclipboard ", visible)
            self.assertIn("\\x1b]52;c;Y2xpcGJvYXJk\\x07", visible)
            self.assertIn("\\x1b[2J c1 \\x9b31m del \\x7f\\r\n", visible)
            self.assertEqual(destination.read_bytes(), markdown.encode("utf-8"))

    def test_policy_change_during_write_approval_blocks_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = project_in(directory)
            (project / "service.py").write_text("VALUE = 1\n", encoding="utf-8")
            (project / "private_zone").mkdir()
            initialize_index(project)
            destination = project / ".silobrief" / "exports" / "policy-change.md"

            def change_policy() -> None:
                register_boundary(
                    "private_zone",
                    "Private zone",
                    "private-zone",
                    start=project,
                )

            _, snapshot, approval_state = load_current_index_for_approval(project)
            try:
                with self.assertRaisesRegex(
                    (OutputBlockedError, SetupError), "settings changed|cannot"
                ):
                    approve_and_write(
                        project,
                        ".silobrief/exports/policy-change.md",
                        rendered_source_brief(),
                        start=project,
                        source_snapshot=snapshot,
                        approval_state=approval_state,
                        input_stream=cast(TextIO, PolicyChangingInput(change_policy)),
                        output_stream=TtyBuffer(),
                    )
            finally:
                approval_state.close()

            self.assertFalse(destination.exists())

    def test_loaded_index_approval_requires_its_reviewed_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = project_in(directory)
            (project / "service.py").write_text("VALUE = 1\n", encoding="utf-8")
            initialize_index(project)
            _, snapshot, approval_state = load_current_index_for_approval(project)
            try:
                for reviewed in (None, replace(snapshot, digest="0" * 64)):
                    with (
                        self.subTest(reviewed=reviewed),
                        self.assertRaisesRegex(OutputBlockedError, "reviewed sources"),
                    ):
                        approve_and_write(
                            project,
                            ".silobrief/exports/mismatch.md",
                            rendered_source_brief(),
                            start=project,
                            source_snapshot=reviewed,
                            approval_state=approval_state,
                            input_stream=TtyBuffer("WRITE\n"),
                            output_stream=TtyBuffer(),
                        )
            finally:
                approval_state.close()

    def test_policy_change_after_file_write_removes_the_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = project_in(directory)
            (project / "service.py").write_text("VALUE = 1\n", encoding="utf-8")
            initialize_index(project)
            destination = project / ".silobrief" / "exports" / "write-race.md"
            original_write = output_module._write_bytes

            def write_then_change_policy(descriptor: int, content: bytes) -> None:
                original_write(descriptor, content)
                mark_index_stale(project)

            _, snapshot, approval_state = load_current_index_for_approval(project)
            try:
                with (
                    mock.patch.object(
                        output_module,
                        "_write_bytes",
                        side_effect=write_then_change_policy,
                    ),
                    self.assertRaisesRegex(
                        (OutputBlockedError, SetupError), "settings changed|cannot"
                    ),
                ):
                    approve_and_write(
                        project,
                        ".silobrief/exports/write-race.md",
                        rendered_source_brief(),
                        start=project,
                        source_snapshot=snapshot,
                        approval_state=approval_state,
                        input_stream=TtyBuffer("WRITE\n"),
                        output_stream=TtyBuffer(),
                    )
            finally:
                approval_state.close()

            self.assertFalse(destination.exists())

    def test_external_output_rejects_root_and_state_aba_during_write_and_publish(self) -> None:
        for target_name in ("root", "state"):
            for phase in ("write", "publish"):
                with (
                    self.subTest(target=target_name, phase=phase),
                    tempfile.TemporaryDirectory() as directory,
                ):
                    base = Path(directory)
                    project = project_in(directory)
                    (project / "service.py").write_text("VALUE = 1\n", encoding="utf-8")
                    initialize_index(project)
                    outside = base / "outside"
                    outside.mkdir()
                    destination = outside / "brief.md"
                    target = project if target_name == "root" else project / ".silobrief"
                    replacement = base / f"replacement-{target_name}-{phase}"
                    replacement.mkdir()
                    attack = AbaSwap(target, replacement)
                    before = descriptor_count()
                    _, snapshot, approval_state = load_current_index_for_approval(project)

                    if phase == "write":
                        patcher = mock.patch.object(
                            output_module,
                            "_write_bytes",
                            side_effect=WriteThenAba(output_module._write_bytes, attack),
                        )
                    else:
                        patcher = mock.patch.object(
                            output_module,
                            "_publish_created_file",
                            side_effect=PublishThenAba(
                                output_module._publish_created_file,
                                attack,
                            ),
                        )

                    try:
                        with patcher:
                            if os.name == "nt":
                                self.assertEqual(
                                    write_external_output(
                                        project,
                                        destination,
                                        snapshot,
                                        approval_state,
                                    ),
                                    WrittenBrief(destination.resolve()),
                                )
                            else:
                                with self.assertRaisesRegex(
                                    OutputBlockedError, "settings changed during approval"
                                ):
                                    write_external_output(
                                        project,
                                        destination,
                                        snapshot,
                                        approval_state,
                                    )
                    finally:
                        approval_state.close()

                    if os.name == "nt":
                        self.assertTrue(attack.blocked)
                        self.assertTrue(destination.is_file())
                    else:
                        self.assertTrue(attack.swapped)
                        self.assertFalse(destination.exists())
                    self.assertEqual(descriptor_count(), before)
                    moved = target.with_name(f"{target.name}-released")
                    target.rename(moved)
                    moved.rename(target)

    @unittest.skipIf(os.name == "nt", "Windows approval handles block state replacement")
    def test_state_aba_never_loads_relaxed_config_or_reads_boundary_source(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            project = project_in(directory)
            (project / "service.py").write_text("VALUE = 1\n", encoding="utf-8")
            private = project / "private_zone"
            private.mkdir()
            (private / "secret.py").write_text("SECRET = 'never read'\n", encoding="utf-8")
            register_boundary("private_zone", "Private zone", "private-zone", start=project)
            initialize_index(project)

            relaxed_project = base / "relaxed"
            relaxed_project.mkdir()
            setup_project(relaxed_project)
            attack = AbaSwap(project / ".silobrief", relaxed_project / ".silobrief")
            original_load = load_source_config
            original_snapshot = snapshot_sources

            def load_relaxed_config(
                root: Path,
                *,
                expected_root_identity: SourceRootIdentity | None = None,
                protected_root_descriptor: int | None = None,
            ) -> tuple[ConfigData, SourceRootIdentity]:
                attack.target.rename(attack.backup)
                attack.replacement.rename(attack.target)
                try:
                    return original_load(
                        root,
                        expected_root_identity=expected_root_identity,
                        protected_root_descriptor=protected_root_descriptor,
                    )
                finally:
                    attack.target.rename(attack.replacement)
                    attack.backup.rename(attack.target)

            relaxed_loader = mock.Mock(side_effect=load_relaxed_config)

            def snapshot_after_state_aba(
                root: Path,
                config: ConfigData,
                *,
                expected_root_identity: SourceRootIdentity | None = None,
                protected_root_descriptor: int | None = None,
            ) -> SourceSnapshot:
                if not relaxed_loader.called:
                    attack()
                return original_snapshot(
                    root,
                    config,
                    expected_root_identity=expected_root_identity,
                    protected_root_descriptor=protected_root_descriptor,
                )

            _, snapshot, approval_state = load_current_index_for_approval(project)
            try:
                with (
                    mock.patch.object(output_module, "load_source_config", relaxed_loader),
                    mock.patch.object(
                        output_module,
                        "snapshot_sources",
                        side_effect=snapshot_after_state_aba,
                    ),
                    mock.patch.object(
                        sources_module,
                        "_read_regular_source",
                        wraps=sources_module._read_regular_source,
                    ) as read_source,
                    self.assertRaisesRegex(
                        OutputBlockedError,
                        "settings changed during approval|project root changed",
                    ),
                ):
                    write_external_output(
                        project,
                        base / "outside.md",
                        snapshot,
                        approval_state,
                    )
            finally:
                approval_state.close()

            relaxed_loader.assert_not_called()
            self.assertTrue(attack.swapped)
            private_reads = [
                call
                for call in read_source.call_args_list
                if call.args[1] == "private_zone/secret.py"
            ]
            self.assertEqual(private_reads, [])

    def test_seal_failure_removes_published_output_and_releases_handles(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            project = project_in(directory)
            (project / "service.py").write_text("VALUE = 1\n", encoding="utf-8")
            initialize_index(project)
            outside = base / "outside"
            outside.mkdir()
            destination = outside / "brief.md"
            before = descriptor_count()
            _, snapshot, approval_state = load_current_index_for_approval(project)

            try:
                with (
                    mock.patch.object(
                        output_module,
                        "seal_current_index_approval",
                        side_effect=CurrentIndexError("forced seal failure"),
                    ),
                    self.assertRaisesRegex(OutputBlockedError, "settings changed during approval"),
                ):
                    approve_and_write(
                        project,
                        str(destination),
                        rendered_source_brief(),
                        start=project,
                        source_snapshot=snapshot,
                        approval_state=approval_state,
                        input_stream=TtyBuffer("WRITE\n"),
                        output_stream=TtyBuffer(),
                    )
            finally:
                approval_state.close()

            self.assertFalse(destination.exists())
            self.assertEqual(descriptor_count(), before)
            moved = project.with_name("project-released")
            project.rename(moved)
            moved.rename(project)

    def test_allows_explicit_output_outside_the_project(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = project_in(directory)
            outside = Path(directory) / "outside"
            outside.mkdir()
            destination = outside / "brief.md"

            result = approve_and_write(
                project,
                str(destination),
                rendered_brief(),
                start=project,
                input_stream=TtyBuffer("WRITE\r\n"),
                output_stream=TtyBuffer(),
            )

            self.assertEqual(result, WrittenBrief(destination.resolve()))
            self.assertTrue(destination.is_file())

    def test_previews_and_writes_source_in_one_file_after_approval(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = project_in(directory)
            (project / "src").mkdir()
            (project / "src" / "api.py").write_text("def run():\n    return 1\n", encoding="utf-8")
            destination = project / ".silobrief" / "exports" / "result.md"
            stdout = TtyBuffer()

            result = approve_and_write(
                project,
                ".silobrief/exports/result.md",
                rendered_source_brief(),
                start=project,
                input_stream=TtyBuffer("WRITE\n"),
                output_stream=stdout,
            )

            self.assertEqual(result, WrittenBrief(destination.resolve()))
            content = destination.read_text(encoding="utf-8")
            self.assertIn("코드를 수정해줘", content)
            self.assertIn("def run():", content)
            self.assertIn("source_delivery: embedded", content)
            self.assertFalse(destination.with_name("result.sources.md").exists())
            self.assertTrue(stdout.getvalue().startswith(content))

    def test_source_change_after_write_approval_blocks_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = project_in(directory)
            source_file = project / "service.py"
            source_file.write_text("VALUE = 1\n", encoding="utf-8")
            baseline = snapshot_sources(project, load_config(project))
            main = project / ".silobrief" / "exports" / "changed.md"

            with self.assertRaisesRegex(OutputBlockedError, "sources changed"):
                approve_and_write(
                    project,
                    ".silobrief/exports/changed.md",
                    rendered_source_brief(),
                    start=project,
                    source_snapshot=baseline,
                    input_stream=cast(TextIO, SourceChangingInput(source_file)),
                    output_stream=TtyBuffer(),
                )

            self.assertFalse(main.exists())

    def test_holds_the_parent_before_a_real_project_root_replacement(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            project = project_in(directory)
            backup = base / "project-backup"
            replacement = base / "replacement"
            replacement.mkdir()
            setup_project(replacement)
            snapshot_then_swap = SnapshotThenReplace(project, backup, replacement)

            try:
                failed = False
                with mock.patch.object(output_module, "_snapshot", side_effect=snapshot_then_swap):
                    try:
                        approve_and_write(
                            project,
                            ".silobrief/exports/result.md",
                            rendered_brief(),
                            start=project,
                            input_stream=TtyBuffer("WRITE\n"),
                            output_stream=TtyBuffer(),
                        )
                    except OutputBlockedError:
                        failed = True
                self.assertTrue(snapshot_then_swap.blocked or snapshot_then_swap.swapped)
                if snapshot_then_swap.swapped:
                    self.assertTrue(failed)
                    replacement_output = project / ".silobrief" / "exports" / "result.md"
                else:
                    replacement_output = replacement / ".silobrief" / "exports" / "result.md"
                self.assertFalse(replacement_output.exists())
            finally:
                moved_replacement = base / "moved-replacement"
                if snapshot_then_swap.swapped and project.exists():
                    project.rename(moved_replacement)
                if backup.exists():
                    backup.rename(project)

    def test_holds_the_parent_before_a_real_output_parent_replacement(self) -> None:
        for final_parent in (False, True):
            with (
                self.subTest(final_parent=final_parent),
                tempfile.TemporaryDirectory() as directory,
            ):
                base = Path(directory)
                project = project_in(directory)
                ancestor = project / ".silobrief" / "exports" / "approved"
                (ancestor / "nested").mkdir(parents=True)
                target = ancestor / "nested" if final_parent else ancestor
                backup = target.with_name(f"{target.name}-backup")
                replacement = base / "replacement"
                replacement.mkdir()
                if not final_parent:
                    (replacement / "nested").mkdir()
                snapshot_then_swap = SnapshotThenReplace(target, backup, replacement)

                try:
                    failed = False
                    with mock.patch.object(
                        output_module, "_snapshot", side_effect=snapshot_then_swap
                    ):
                        try:
                            approve_and_write(
                                project,
                                ".silobrief/exports/approved/nested/result.md",
                                rendered_brief(),
                                start=project,
                                input_stream=TtyBuffer("WRITE\n"),
                                output_stream=TtyBuffer(),
                            )
                        except OutputBlockedError:
                            failed = True
                    self.assertTrue(snapshot_then_swap.blocked or snapshot_then_swap.swapped)
                    if snapshot_then_swap.swapped:
                        self.assertTrue(failed)
                        replacement_output = ancestor / "nested" / "result.md"
                    else:
                        replacement_output = replacement / (
                            "result.md" if final_parent else "nested/result.md"
                        )
                    self.assertFalse(replacement_output.exists())
                finally:
                    moved_replacement = base / "moved-replacement"
                    if snapshot_then_swap.swapped and target.exists():
                        target.rename(moved_replacement)
                    if backup.exists():
                        backup.rename(target)

    @unittest.skipIf(os.name == "nt", "POSIX permits replacing an open directory")
    def test_holds_the_parent_when_its_identity_value_is_reused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = project_in(directory)
            parent = project / ".silobrief" / "exports"
            original_snapshot = output_module._snapshot
            snapshot_calls = 0

            def snapshot_then_recreate(
                root: Path,
                *,
                expected_root_identity: SourceRootIdentity | None = None,
            ) -> SourceSnapshot:
                nonlocal snapshot_calls
                snapshot = original_snapshot(
                    root,
                    expected_root_identity=expected_root_identity,
                )
                snapshot_calls += 1
                if snapshot_calls == 1:
                    parent.rmdir()
                    parent.mkdir(mode=0o777)
                return snapshot

            with (
                mock.patch.object(output_module, "_directory_identity", return_value=(1, 1)),
                mock.patch.object(
                    output_module,
                    "_snapshot",
                    side_effect=snapshot_then_recreate,
                ),
                self.assertRaises(OutputBlockedError),
            ):
                approve_and_write(
                    project,
                    ".silobrief/exports/result.md",
                    rendered_brief(),
                    start=project,
                    input_stream=TtyBuffer("WRITE\n"),
                    output_stream=TtyBuffer(),
                )

            self.assertFalse((parent / "result.md").exists())

    @unittest.skipIf(os.name == "nt", "POSIX permits replacing an open directory")
    def test_holds_the_parent_during_location_policy_checks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = project_in(directory)
            parent = project / ".silobrief" / "exports"
            original_check = output_module._require_allowed_location

            def recreate_then_check(destination: Path, root: Path) -> None:
                parent.rmdir()
                parent.mkdir(mode=0o777)
                original_check(destination, root)

            with (
                mock.patch.object(output_module, "_directory_identity", return_value=(1, 1)),
                mock.patch.object(
                    output_module,
                    "_require_allowed_location",
                    side_effect=recreate_then_check,
                ),
                self.assertRaises(OutputBlockedError),
            ):
                approve_and_write(
                    project,
                    ".silobrief/exports/result.md",
                    rendered_brief(),
                    start=project,
                    input_stream=TtyBuffer("WRITE\n"),
                    output_stream=TtyBuffer(),
                )

            self.assertFalse((parent / "result.md").exists())

    @unittest.skipUnless(os.name == "nt", "Windows directory handle test")
    def test_locks_the_parent_during_location_policy_checks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = project_in(directory)
            parent = project / ".silobrief" / "exports"
            backup = parent.with_name("exports-backup")
            original_check = output_module._require_allowed_location
            swap_blocked = False

            def replace_then_check(destination: Path, root: Path) -> None:
                nonlocal swap_blocked
                try:
                    parent.rename(backup)
                except OSError:
                    swap_blocked = True
                original_check(destination, root)

            with mock.patch.object(
                output_module,
                "_require_allowed_location",
                side_effect=replace_then_check,
            ):
                approve_and_write(
                    project,
                    ".silobrief/exports/result.md",
                    rendered_brief(),
                    start=project,
                    input_stream=TtyBuffer("WRITE\n"),
                    output_stream=TtyBuffer(),
                )

            self.assertTrue(swap_blocked)
            self.assertTrue((parent / "result.md").is_file())

    @unittest.skipIf(os.name == "nt", "POSIX permits renaming an open directory")
    def test_rejects_a_real_parent_replacement_after_protection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = project_in(directory)
            parent = project / ".silobrief" / "exports" / "approved"
            parent.mkdir()
            backup = parent.with_name("approved-backup")
            replacement = Path(directory) / "replacement"
            replacement.mkdir()

            try:
                with self.assertRaisesRegex(OutputBlockedError, "output parent changed"):
                    approve_and_write(
                        project,
                        ".silobrief/exports/approved/result.md",
                        rendered_brief(),
                        start=project,
                        input_stream=cast(
                            TextIO,
                            RealDirectoryReplacingInput(parent, backup, replacement),
                        ),
                        output_stream=TtyBuffer(),
                    )
                self.assertFalse((parent / "result.md").exists())
                self.assertFalse((backup / "result.md").exists())
            finally:
                moved_replacement = Path(directory) / "moved-replacement"
                if parent.exists():
                    parent.rename(moved_replacement)
                if backup.exists():
                    backup.rename(parent)

    @unittest.skipIf(os.name == "nt", "POSIX permits renaming an open directory")
    def test_revalidates_the_parent_after_file_creation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = project_in(directory)
            parent = project / ".silobrief" / "exports" / "approved"
            parent.mkdir()
            backup = parent.with_name("approved-backup")
            replacement = Path(directory) / "replacement"
            replacement.mkdir()
            original_write = output_module._write_new_file

            def write_then_replace(
                path: Path,
                content: str,
                *,
                directory_guard: output_module._OutputDirectoryGuard,
            ) -> None:
                original_write(path, content, directory_guard=directory_guard)
                parent.rename(backup)
                replacement.rename(parent)

            try:
                with (
                    mock.patch.object(
                        output_module, "_write_new_file", side_effect=write_then_replace
                    ),
                    self.assertRaisesRegex(OutputBlockedError, "after creating"),
                ):
                    approve_and_write(
                        project,
                        ".silobrief/exports/approved/result.md",
                        rendered_brief(),
                        start=project,
                        input_stream=TtyBuffer("WRITE\n"),
                        output_stream=TtyBuffer(),
                    )
                self.assertFalse((parent / "result.md").exists())
                self.assertFalse((backup / "result.md").exists())
            finally:
                moved_replacement = Path(directory) / "moved-replacement"
                if parent.exists():
                    parent.rename(moved_replacement)
                if backup.exists():
                    backup.rename(parent)

    @unittest.skipIf(os.name == "nt", "POSIX permits replacing an open directory")
    def test_revalidates_final_and_intermediate_parents_after_publication(self) -> None:
        for final_parent in (False, True):
            for use_symlink in (False, True):
                with (
                    self.subTest(final_parent=final_parent, use_symlink=use_symlink),
                    tempfile.TemporaryDirectory() as directory,
                ):
                    base = Path(directory)
                    project = project_in(directory)
                    ancestor = project / ".silobrief" / "exports" / "approved"
                    parent = ancestor / "nested"
                    parent.mkdir(parents=True)
                    target = parent if final_parent else ancestor
                    backup = target.with_name(f"{target.name}-backup")
                    replacement = base / "replacement"
                    replacement.mkdir()
                    if not final_parent:
                        (replacement / "nested").mkdir()
                    publish_then_replace = PublishThenReplace(
                        target,
                        backup,
                        replacement,
                        final_parent=final_parent,
                        use_symlink=use_symlink,
                    )

                    descriptor_count = len(os.listdir("/proc/self/fd"))
                    try:
                        with (
                            mock.patch.object(
                                output_module,
                                "_publish_created_file",
                                side_effect=publish_then_replace,
                            ),
                            self.assertRaisesRegex(
                                OutputBlockedError,
                                "output parent changed while publishing",
                            ),
                        ):
                            approve_and_write(
                                project,
                                ".silobrief/exports/approved/nested/result.md",
                                rendered_brief(),
                                start=project,
                                input_stream=TtyBuffer("WRITE\n"),
                                output_stream=TtyBuffer(),
                            )

                        current_parent = target if final_parent else target / "nested"
                        self.assertEqual(
                            (current_parent / "result.md").read_text(encoding="utf-8"),
                            "rival content",
                        )
                        moved_parent = backup if final_parent else backup / "nested"
                        moved_output = moved_parent / "result.md"
                        if moved_output.exists():
                            self.assertEqual(moved_output.read_bytes(), b"")
                        self.assertEqual(
                            len(os.listdir("/proc/self/fd")),
                            descriptor_count,
                        )
                    finally:
                        if target.is_symlink():
                            target.unlink()
                        elif target.exists():
                            target.rename(base / "used-replacement")
                        if backup.exists():
                            backup.rename(target)

    @unittest.skipIf(os.name == "nt", "POSIX anonymous output test")
    def test_reports_missing_otmpfile_support_explicitly(self) -> None:
        with (
            mock.patch.object(
                os,
                "open",
                side_effect=OSError(errno.EOPNOTSUPP, "not supported"),
            ),
            self.assertRaisesRegex(OutputBlockedError, "does not support O_TMPFILE"),
        ):
            output_module._open_new_file(Path("result.md"), 7)

    @unittest.skipIf(os.name == "nt", "POSIX proc-fd publication test")
    def test_reports_missing_proc_fd_linking_and_removes_anonymous_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = project_in(directory)
            destination = project / ".silobrief" / "exports" / "result.md"
            descriptor_count = len(os.listdir("/proc/self/fd"))

            with (
                mock.patch.object(
                    os,
                    "link",
                    side_effect=OSError(errno.ENOENT, "proc fd unavailable"),
                ),
                self.assertRaisesRegex(OutputBlockedError, "/proc/self/fd linking"),
            ):
                approve_and_write(
                    project,
                    ".silobrief/exports/result.md",
                    rendered_brief(),
                    start=project,
                    input_stream=TtyBuffer("WRITE\n"),
                    output_stream=TtyBuffer(),
                )

            self.assertFalse(destination.exists())
            self.assertEqual(len(os.listdir("/proc/self/fd")), descriptor_count)

    def test_rejects_a_replaced_created_file_and_preserves_the_rival(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = project_in(directory)
            destination = project / ".silobrief" / "exports" / "result.md"
            moved = Path(directory) / "moved-result.md"
            original_write = output_module._write_new_file
            swap_blocked = False

            def write_then_replace(
                path: Path,
                content: str,
                *,
                directory_guard: output_module._OutputDirectoryGuard,
            ) -> None:
                nonlocal swap_blocked
                original_write(path, content, directory_guard=directory_guard)
                created = directory_guard.created
                self.assertIsNotNone(created)
                if os.name == "nt":
                    try:
                        path.rename(moved)
                    except OSError:
                        swap_blocked = True
                        return
                path.write_text("rival content", encoding="utf-8")

            with mock.patch.object(
                output_module,
                "_write_new_file",
                side_effect=write_then_replace,
            ):
                if os.name == "nt":
                    approve_and_write(
                        project,
                        ".silobrief/exports/result.md",
                        rendered_brief(),
                        start=project,
                        input_stream=TtyBuffer("WRITE\n"),
                        output_stream=TtyBuffer(),
                    )
                else:
                    with self.assertRaisesRegex(
                        OutputBlockedError,
                        "output path already exists",
                    ):
                        approve_and_write(
                            project,
                            ".silobrief/exports/result.md",
                            rendered_brief(),
                            start=project,
                            input_stream=TtyBuffer("WRITE\n"),
                            output_stream=TtyBuffer(),
                        )

            if os.name == "nt":
                self.assertTrue(swap_blocked)
                self.assertEqual(
                    destination.read_text(encoding="utf-8"),
                    rendered_brief().markdown,
                )
            else:
                self.assertEqual(destination.read_text(encoding="utf-8"), "rival content")
            self.assertFalse(moved.exists())

    def test_rejects_a_hardlinked_created_file_and_erases_its_content(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = project_in(directory)
            destination = project / ".silobrief" / "exports" / "result.md"
            moved = project / ".silobrief" / "exports" / "moved-result.md"
            original_write = output_module._write_new_file

            def write_then_link(
                path: Path,
                content: str,
                *,
                directory_guard: output_module._OutputDirectoryGuard,
            ) -> None:
                original_write(path, content, directory_guard=directory_guard)
                created = directory_guard.created
                self.assertIsNotNone(created)
                assert created is not None
                try:
                    if os.name == "nt":
                        os.link(path, moved)
                    else:
                        self.assertIsNotNone(directory_guard.descriptor)
                        os.link(
                            f"/proc/self/fd/{created.descriptor}",
                            moved.name,
                            dst_dir_fd=directory_guard.descriptor,
                            follow_symlinks=True,
                        )
                        os.link(
                            moved.name,
                            path.name,
                            src_dir_fd=directory_guard.descriptor,
                            dst_dir_fd=directory_guard.descriptor,
                            follow_symlinks=False,
                        )
                except OSError as error:
                    self.skipTest(f"hard links are unavailable: {error}")

            with (
                mock.patch.object(
                    output_module,
                    "_write_new_file",
                    side_effect=write_then_link,
                ),
                self.assertRaisesRegex(OutputBlockedError, "output file changed"),
            ):
                approve_and_write(
                    project,
                    ".silobrief/exports/result.md",
                    rendered_brief(),
                    start=project,
                    input_stream=TtyBuffer("WRITE\n"),
                    output_stream=TtyBuffer(),
                )

            for path in (destination, moved):
                if path.exists():
                    self.assertEqual(path.read_bytes(), b"")

    def test_cleans_a_partial_file_after_keyboard_interrupt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = project_in(directory)
            destination = project / ".silobrief" / "exports" / "partial.md"
            original_write = os.write
            write_calls = 0

            def interrupt_partial_write(descriptor: int, content: bytes) -> int:
                nonlocal write_calls
                write_calls += 1
                if write_calls == 1:
                    return original_write(descriptor, content[:16])
                raise KeyboardInterrupt

            with (
                mock.patch.object(os, "write", side_effect=interrupt_partial_write),
                self.assertRaises(KeyboardInterrupt),
            ):
                approve_and_write(
                    project,
                    ".silobrief/exports/partial.md",
                    rendered_brief(),
                    start=project,
                    input_stream=TtyBuffer("WRITE\n"),
                    output_stream=TtyBuffer(),
                )

            self.assertGreater(write_calls, 1)
            self.assertFalse(destination.exists())

    def test_cleans_a_created_file_after_base_exception(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = project_in(directory)
            destination = project / ".silobrief" / "exports" / "interrupted.md"
            original_write = output_module._write_new_file

            def write_then_interrupt(
                path: Path,
                content: str,
                *,
                directory_guard: output_module._OutputDirectoryGuard,
            ) -> None:
                original_write(path, content, directory_guard=directory_guard)
                raise KeyboardInterrupt

            with (
                mock.patch.object(
                    output_module,
                    "_write_new_file",
                    side_effect=write_then_interrupt,
                ),
                self.assertRaises(KeyboardInterrupt),
            ):
                approve_and_write(
                    project,
                    ".silobrief/exports/interrupted.md",
                    rendered_brief(),
                    start=project,
                    input_stream=TtyBuffer("WRITE\n"),
                    output_stream=TtyBuffer(),
                )

            self.assertFalse(destination.exists())

    def test_cleans_a_fully_written_file_before_write_returns(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = project_in(directory)
            destination = project / ".silobrief" / "exports" / "system-exit.md"
            original_write = output_module._write_bytes

            def write_then_exit(descriptor: int, content: bytes) -> None:
                original_write(descriptor, content)
                raise SystemExit(7)

            with (
                mock.patch.object(
                    output_module,
                    "_write_bytes",
                    side_effect=write_then_exit,
                ),
                self.assertRaises(SystemExit),
            ):
                approve_and_write(
                    project,
                    ".silobrief/exports/system-exit.md",
                    rendered_brief(),
                    start=project,
                    input_stream=TtyBuffer("WRITE\n"),
                    output_stream=TtyBuffer(),
                )

            self.assertFalse(destination.exists())

    def test_main_race_preserves_the_rival_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = project_in(directory)
            main = project / ".silobrief" / "exports" / "race.md"

            with self.assertRaisesRegex(OutputBlockedError, "already exists"):
                approve_and_write(
                    project,
                    ".silobrief/exports/race.md",
                    rendered_source_brief(),
                    start=project,
                    input_stream=cast(TextIO, RacingInput(main)),
                    output_stream=TtyBuffer(),
                )

            self.assertEqual(main.read_text(encoding="utf-8"), "rival content")

    def test_requires_both_ttys_and_an_exact_approval(self) -> None:
        cases = (
            (False, True, "WRITE\n"),
            (True, False, "WRITE\n"),
            (True, True, "write\n"),
            (True, True, " WRITE\n"),
            (True, True, "WRITE \n"),
            (True, True, "YES\n"),
            (True, True, ""),
        )
        with tempfile.TemporaryDirectory() as directory:
            project = project_in(directory)
            exports = project / ".silobrief" / "exports"
            before = tuple(exports.iterdir())

            for number, (input_tty, output_tty, approval) in enumerate(cases):
                with self.subTest(approval=approval, input_tty=input_tty, output_tty=output_tty):
                    destination = f".silobrief/exports/refused-{number}.md"
                    with self.assertRaises(OutputBlockedError):
                        approve_and_write(
                            project,
                            destination,
                            rendered_brief(),
                            start=project,
                            input_stream=TtyBuffer(approval, tty=input_tty),
                            output_stream=TtyBuffer(tty=output_tty),
                        )
                    self.assertFalse((project / destination).exists())
                    self.assertEqual(tuple(exports.iterdir()), before)

    def test_rejects_invalid_and_existing_output_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = project_in(directory)
            outside = Path(directory) / "outside"
            outside.mkdir()
            existing = project / ".silobrief" / "exports" / "existing.md"
            existing.write_text("keep this", encoding="utf-8")
            existing_directory = project / ".silobrief" / "exports" / "folder.md"
            existing_directory.mkdir()
            cases = (
                "result.md",
                ".silobrief/exports/result.txt",
                ".silobrief/exports/result.MD",
                ".silobrief/exports/missing/result.md",
                "../outside/traversal.md",
                ".silobrief/exports\\mixed.md",
                ".silobrief/exports/existing.md",
                ".silobrief/exports/folder.md",
            )

            for output in cases:
                with self.subTest(output=output):
                    with self.assertRaises(OutputBlockedError):
                        approve_and_write(
                            project,
                            output,
                            rendered_brief(),
                            start=project,
                            input_stream=TtyBuffer("WRITE\n"),
                            output_stream=TtyBuffer(),
                        )
            self.assertEqual(existing.read_text(encoding="utf-8"), "keep this")
            self.assertTrue(existing_directory.is_dir())
            self.assertFalse((outside / "traversal.md").exists())

    def test_exclusive_creation_blocks_a_file_created_during_approval(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = project_in(directory)
            destination = project / ".silobrief" / "exports" / "race.md"

            with self.assertRaisesRegex(OutputBlockedError, "already exists"):
                approve_and_write(
                    project,
                    ".silobrief/exports/race.md",
                    rendered_brief(),
                    start=project,
                    input_stream=cast(TextIO, RacingInput(destination)),
                    output_stream=TtyBuffer(),
                )

            self.assertEqual(destination.read_text(encoding="utf-8"), "rival content")

    def test_rejects_output_and_parent_symbolic_links(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = project_in(directory)
            exports = project / ".silobrief" / "exports"
            outside = Path(directory) / "outside"
            outside.mkdir()
            target = outside / "target.md"
            target.write_text("target content", encoding="utf-8")
            output_link = exports / "linked.md"
            parent_link = exports / "linked-parent"
            try:
                output_link.symlink_to(target)
                parent_link.symlink_to(outside, target_is_directory=True)
            except OSError as error:
                self.skipTest(f"symbolic links are unavailable: {error}")

            for output, rendered in (
                (".silobrief/exports/linked.md", rendered_brief()),
                (".silobrief/exports/linked-parent/result.md", rendered_brief()),
            ):
                with self.subTest(output=output):
                    with self.assertRaisesRegex(OutputBlockedError, "symbolic link"):
                        approve_and_write(
                            project,
                            output,
                            rendered,
                            start=project,
                            input_stream=TtyBuffer("WRITE\n"),
                            output_stream=TtyBuffer(),
                        )
            self.assertEqual(target.read_text(encoding="utf-8"), "target content")
            self.assertFalse((outside / "result.md").exists())

    @unittest.skipUnless(os.name == "nt", "directory junctions require Windows")
    def test_rejects_a_junction_in_the_output_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = project_in(directory)
            exports = project / ".silobrief" / "exports"
            outside = Path(directory) / "outside"
            outside.mkdir()

            with directory_junction(exports / "linked-parent", outside):
                with self.assertRaisesRegex(OutputBlockedError, "reparse point"):
                    approve_and_write(
                        project,
                        ".silobrief/exports/linked-parent/result.md",
                        rendered_brief(),
                        start=project,
                        input_stream=TtyBuffer("WRITE\n"),
                        output_stream=TtyBuffer(),
                    )

            self.assertFalse((outside / "result.md").exists())

    @unittest.skipIf(os.name == "nt", "POSIX symbolic-link race test")
    def test_rejects_an_intermediate_symlink_before_parent_protection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = project_in(directory)
            ancestor = project / ".silobrief" / "exports" / "approved"
            (ancestor / "nested").mkdir(parents=True)
            backup = ancestor.with_name("approved-backup")
            outside = Path(directory) / "outside"
            (outside / "nested").mkdir(parents=True)
            original_snapshot = output_module._snapshot
            snapshot_calls = 0

            def snapshot_then_swap(
                root: Path,
                *,
                expected_root_identity: SourceRootIdentity | None = None,
            ) -> SourceSnapshot:
                nonlocal snapshot_calls
                snapshot = original_snapshot(
                    root,
                    expected_root_identity=expected_root_identity,
                )
                snapshot_calls += 1
                if snapshot_calls == 1:
                    ancestor.rename(backup)
                    ancestor.symlink_to(outside, target_is_directory=True)
                return snapshot

            try:
                with (
                    mock.patch.object(output_module, "_snapshot", side_effect=snapshot_then_swap),
                    self.assertRaisesRegex(OutputBlockedError, "output parent"),
                ):
                    approve_and_write(
                        project,
                        ".silobrief/exports/approved/nested/result.md",
                        rendered_brief(),
                        start=project,
                        input_stream=TtyBuffer("WRITE\n"),
                        output_stream=TtyBuffer(),
                    )
            finally:
                if ancestor.is_symlink():
                    ancestor.unlink()
                if backup.exists():
                    backup.rename(ancestor)

            self.assertFalse((outside / "nested" / "result.md").exists())
            self.assertFalse((ancestor / "nested" / "result.md").exists())

    @unittest.skipUnless(os.name == "nt", "directory junctions require Windows")
    def test_holds_the_parent_before_an_intermediate_junction_replacement(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = project_in(directory)
            ancestor = project / ".silobrief" / "exports" / "approved"
            (ancestor / "nested").mkdir(parents=True)
            backup = ancestor.with_name("approved-backup")
            outside = Path(directory) / "outside"
            (outside / "nested").mkdir(parents=True)
            original_snapshot = output_module._snapshot
            snapshot_calls = 0
            swap_blocked = False
            swapped = False

            try:
                with ExitStack() as junctions:

                    def snapshot_then_swap(
                        root: Path,
                        *,
                        expected_root_identity: SourceRootIdentity | None = None,
                    ) -> SourceSnapshot:
                        nonlocal snapshot_calls, swap_blocked, swapped
                        snapshot = original_snapshot(
                            root,
                            expected_root_identity=expected_root_identity,
                        )
                        snapshot_calls += 1
                        if snapshot_calls == 1:
                            try:
                                ancestor.rename(backup)
                            except OSError:
                                swap_blocked = True
                            else:
                                swapped = True
                                junctions.enter_context(directory_junction(ancestor, outside))
                        return snapshot

                    failed = False
                    with mock.patch.object(
                        output_module,
                        "_snapshot",
                        side_effect=snapshot_then_swap,
                    ):
                        try:
                            approve_and_write(
                                project,
                                ".silobrief/exports/approved/nested/result.md",
                                rendered_brief(),
                                start=project,
                                input_stream=TtyBuffer("WRITE\n"),
                                output_stream=TtyBuffer(),
                            )
                        except OutputBlockedError:
                            failed = True
            finally:
                if backup.exists():
                    backup.rename(ancestor)

            self.assertTrue(swap_blocked or swapped)
            if swapped:
                self.assertTrue(failed)
            self.assertFalse((outside / "nested" / "result.md").exists())

    @unittest.skipUnless(os.name == "nt", "directory junctions require Windows")
    def test_locks_the_output_parent_during_interactive_approval(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = project_in(directory)
            parent = project / ".silobrief" / "exports" / "approved"
            parent.mkdir()
            backup = parent.with_name("approved-backup")
            outside = Path(directory) / "outside"
            outside.mkdir()
            result: WrittenBrief | None = None

            try:
                with ExitStack() as junctions:
                    approval = ParentReplacingInput(parent, backup, outside, junctions)
                    result = approve_and_write(
                        project,
                        ".silobrief/exports/approved/result.md",
                        rendered_brief(),
                        start=project,
                        input_stream=cast(TextIO, approval),
                        output_stream=TtyBuffer(),
                    )
            finally:
                if backup.exists():
                    backup.rename(parent)

            self.assertIsNotNone(result)
            self.assertTrue(approval.swap_blocked)
            self.assertFalse(approval.swapped)
            self.assertFalse((outside / "result.md").exists())
            self.assertEqual(
                (parent / "result.md").read_bytes(),
                rendered_brief().markdown.encode("utf-8"),
            )


if __name__ == "__main__":
    unittest.main()
