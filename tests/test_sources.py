from __future__ import annotations

import hashlib
import os
import tempfile
import unittest
from pathlib import Path
from typing import cast
from unittest import mock

import silobrief.sources as sources
from silobrief.boundaries import register_boundary
from silobrief.sources import SourceWarning, compare_snapshots, snapshot_sources
from silobrief.state import load_config, setup_project


def file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class SourceSnapshotTests(unittest.TestCase):
    def test_snapshot_skips_excluded_trees_before_scan_or_read(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            (project / "package").mkdir()
            (project / "package" / "visible.py").write_text("VISIBLE = 1\n", encoding="utf-8")
            (project / "allowed.py").write_text("ALLOWED = 1\n", encoding="utf-8")
            (project / "notes.txt").write_text("not source\n", encoding="utf-8")
            private = project / "private"
            private.mkdir()
            (private / "secret.py").write_text("BOUNDARY_CANARY\n", encoding="utf-8")
            private_file = project / "private_file.py"
            private_file.write_text("FILE_BOUNDARY_CANARY\n", encoding="utf-8")
            build = project / "package" / "build"
            build.mkdir()
            (build / "generated.py").write_text("DEFAULT_CANARY\n", encoding="utf-8")
            setup_project(project)
            register_boundary("private", "Private implementation", "private-code", start=project)
            register_boundary(
                "private_file.py",
                "Private source file",
                "private-file",
                start=project,
            )
            config = load_config(project)

            with (
                mock.patch("silobrief.sources.os.scandir", wraps=os.scandir) as scan,
                mock.patch(
                    "silobrief.sources._read_regular_source",
                    wraps=sources._read_regular_source,
                ) as read_source,
            ):
                snapshot = snapshot_sources(project, config)

            resolved_project = project.resolve()
            scanned = {
                Path(cast(str | os.PathLike[str], call.args[0]))
                .resolve()
                .relative_to(resolved_project)
                .as_posix()
                for call in scan.call_args_list
            }
            opened = {
                Path(cast(Path, call.args[0])).resolve().relative_to(resolved_project).as_posix()
                for call in read_source.call_args_list
            }
            self.assertEqual(
                [source.path for source in snapshot.files], ["allowed.py", "package/visible.py"]
            )
            self.assertEqual(opened, {"allowed.py", "package/visible.py"})
            self.assertNotIn("private", scanned)
            self.assertNotIn("package/build", scanned)
            self.assertNotIn(".silobrief", scanned)
            collected = b"".join(source.content for source in snapshot.files)
            self.assertNotIn(b"BOUNDARY_CANARY", collected)
            self.assertNotIn(b"FILE_BOUNDARY_CANARY", collected)
            self.assertNotIn(b"DEFAULT_CANARY", collected)

    def test_snapshot_is_deterministic_and_uses_posix_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            package = project / "package"
            package.mkdir()
            (project / "z.py").write_bytes(b"VALUE = 26\n")
            (project / "a.py").write_bytes(b"VALUE = 1\n")
            (package / "module.py").write_bytes(b"VALUE = 2\n")
            setup_project(project)
            config = load_config(project)

            first = snapshot_sources(project, config)
            second = snapshot_sources(project, config)

            self.assertEqual(first, second)
            self.assertEqual(
                [source.path for source in first.files],
                ["a.py", "package/module.py", "z.py"],
            )
            self.assertEqual(
                first.digest,
                "492afd37cb3a7e918d1399bdf560cb72f46da2dd2a793ba80b0afb31efefa427",
            )

    def test_snapshot_digest_includes_relative_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            source = project / "before.py"
            source.write_bytes(b"VALUE = 1\n")
            setup_project(project)
            config = load_config(project)
            before = snapshot_sources(project, config)

            source.rename(project / "after.py")
            after = snapshot_sources(project, config)
            changes = compare_snapshots(before, after)

            self.assertNotEqual(before.digest, after.digest)
            self.assertEqual(changes.added, ("after.py",))
            self.assertEqual(changes.removed, ("before.py",))
            self.assertEqual(changes.modified, ())
            self.assertTrue(changes.has_changes)

    def test_compare_snapshots_reports_added_removed_and_modified_sources(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            (project / "changed.py").write_bytes(b"VALUE = 1\n")
            (project / "removed.py").write_bytes(b"VALUE = 2\n")
            setup_project(project)
            config = load_config(project)
            before = snapshot_sources(project, config)

            (project / "changed.py").write_bytes(b"VALUE = 3\n")
            (project / "removed.py").unlink()
            (project / "added.py").write_bytes(b"VALUE = 4\n")
            after = snapshot_sources(project, config)
            changes = compare_snapshots(before, after)

            self.assertEqual(changes.added, ("added.py",))
            self.assertEqual(changes.removed, ("removed.py",))
            self.assertEqual(changes.modified, ("changed.py",))
            self.assertTrue(changes.has_changes)
            self.assertFalse(compare_snapshots(after, after).has_changes)

    def test_snapshot_does_not_modify_source_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            source = project / "service.py"
            source.write_bytes(b"VALUE = 1\n")
            setup_project(project)
            config = load_config(project)
            before = (file_digest(source), source.stat().st_mtime_ns)

            snapshot_sources(project, config)

            self.assertEqual((file_digest(source), source.stat().st_mtime_ns), before)

    def test_snapshot_warns_about_symlinks_without_reading_targets(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project"
            project.mkdir()
            outside_file = root / "outside.py"
            outside_file.write_bytes(b"OUTSIDE_FILE_CANARY\n")
            outside_directory = root / "outside-directory"
            outside_directory.mkdir()
            (outside_directory / "module.py").write_bytes(b"OUTSIDE_DIRECTORY_CANARY\n")
            file_link = project / "linked.py"
            directory_link = project / "linked-directory"
            try:
                file_link.symlink_to(outside_file)
                directory_link.symlink_to(outside_directory, target_is_directory=True)
            except OSError as error:
                self.skipTest(f"symbolic links unavailable: {error}")
            setup_project(project)
            config = load_config(project)

            snapshot = snapshot_sources(project, config)

            self.assertEqual(snapshot.files, ())
            self.assertEqual(
                snapshot.warnings,
                (
                    SourceWarning(path="linked-directory", reason="symbolic link skipped"),
                    SourceWarning(path="linked.py", reason="symbolic link skipped"),
                ),
            )


if __name__ == "__main__":
    unittest.main()
