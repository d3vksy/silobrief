from __future__ import annotations

import hashlib
import os
import tempfile
import unittest
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from pathlib import Path
from typing import cast
from unittest import mock

import silobrief.sources as sources
from silobrief.boundaries import register_boundary
from silobrief.sources import (
    SourceCollectionError,
    SourceWarning,
    compare_snapshots,
    load_source_config,
    snapshot_sources,
)
from silobrief.state import ConfigData, load_config, setup_project
from tests.windows_junctions import directory_junction


def file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@contextmanager
def swapped_directory(path: Path, target: Path) -> Iterator[None]:
    parked = path.with_name(f"{path.name}-parked")
    path.rename(parked)
    try:
        if os.name == "nt":
            with directory_junction(path, target):
                yield
        else:
            path.symlink_to(target, target_is_directory=True)
            try:
                yield
            finally:
                path.unlink()
    finally:
        if not path.exists():
            parked.rename(path)


@contextmanager
def swapped_real_directory(path: Path, replacement: Path) -> Iterator[None]:
    parked = path.with_name(f"{path.name}-parked")
    path.rename(parked)
    replacement.rename(path)
    try:
        yield
    finally:
        path.rename(replacement)
        parked.rename(path)


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
                mock.patch(
                    "silobrief.sources._scan_directory",
                    wraps=sources._scan_directory,
                ) as scan,
                mock.patch(
                    "silobrief.sources._read_regular_source",
                    wraps=sources._read_regular_source,
                ) as read_source,
            ):
                snapshot = snapshot_sources(project, config)

            resolved_project = project.resolve()
            scanned = {
                cast(sources._SourceDirectory, call.args[0])
                .expected_path.relative_to(resolved_project)
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

    @unittest.skipUnless(os.name == "nt", "Windows path matching is case-insensitive")
    def test_snapshot_skips_a_boundary_after_a_case_only_rename(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            private = project / "Private"
            private.mkdir()
            (private / "secret.py").write_bytes(b"CASE_BOUNDARY_CANARY\n")
            (project / "allowed.py").write_bytes(b"ALLOWED\n")
            setup_project(project)
            register_boundary("Private", "Private implementation", "private", start=project)
            config = load_config(project)
            self.assertEqual(config["boundaries"][0]["path"], "Private")

            temporary = project / "case-rename"
            private.rename(temporary)
            renamed = project / "private"
            temporary.rename(renamed)

            with (
                mock.patch("silobrief.sources.os.scandir", wraps=os.scandir) as scan,
                mock.patch(
                    "silobrief.sources._read_regular_source",
                    wraps=sources._read_regular_source,
                ) as read_source,
            ):
                snapshot = snapshot_sources(project, config)

            self.assertEqual([source.path for source in snapshot.files], ["allowed.py"])
            self.assertEqual(scan.call_count, 1)
            self.assertEqual(
                [cast(str, call.args[1]) for call in read_source.call_args_list],
                ["allowed.py"],
            )

    @unittest.skipIf(os.name == "nt", "POSIX boundary paths are case-sensitive")
    def test_snapshot_keeps_posix_boundary_matching_case_sensitive(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            private = project / "Private"
            private.mkdir()
            (private / "secret.py").write_bytes(b"BOUNDARY_CANARY\n")
            public = project / "private"
            public.mkdir()
            (public / "visible.py").write_bytes(b"VISIBLE\n")
            setup_project(project)
            register_boundary("Private", "Private implementation", "private", start=project)

            snapshot = snapshot_sources(project, load_config(project))

            self.assertEqual([source.path for source in snapshot.files], ["private/visible.py"])

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

    @unittest.skipUnless(os.name == "nt", "directory junctions require Windows")
    def test_snapshot_skips_directory_junctions_without_reading_targets(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project"
            project.mkdir()
            outside = root / "outside"
            outside.mkdir()
            (outside / "secret.py").write_bytes(b"JUNCTION_CANARY\n")
            setup_project(project)
            config = load_config(project)

            with directory_junction(project / "linked", outside):
                snapshot = snapshot_sources(project, config)

            self.assertEqual(snapshot.files, ())
            self.assertEqual(
                snapshot.warnings,
                (SourceWarning(path="linked", reason="reparse point skipped"),),
            )
            self.assertNotIn(b"JUNCTION_CANARY", repr(snapshot).encode())

    @unittest.skipUnless(os.name == "nt", "directory junctions require Windows")
    def test_snapshot_rejects_a_directory_replaced_during_scan(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project"
            project.mkdir()
            package = project / "package"
            package.mkdir()
            outside = root / "outside"
            outside.mkdir()
            (outside / "secret.py").write_bytes(b"SWAPPED_DIRECTORY_CANARY\n")
            setup_project(project)
            config = load_config(project)
            original_scandir = os.scandir
            swapped = False

            with ExitStack() as junctions:

                def swap_before_scan(
                    path: str | os.PathLike[str],
                ) -> Iterator[os.DirEntry[str]]:
                    nonlocal swapped
                    if Path(path) == package and not swapped:
                        swapped = True
                        package.rmdir()
                        junctions.enter_context(directory_junction(package, outside))
                    return original_scandir(path)

                with (
                    mock.patch("silobrief.sources.os.scandir", side_effect=swap_before_scan),
                    mock.patch(
                        "silobrief.sources._read_regular_source",
                        wraps=sources._read_regular_source,
                    ) as read_source,
                ):
                    with self.assertRaisesRegex(
                        SourceCollectionError,
                        "source directory changed during traversal|cannot (inspect|scan) source",
                    ):
                        snapshot_sources(project, config)

                self.assertFalse(read_source.called)

    @unittest.skipUnless(os.name == "nt", "Windows entry IDs are required")
    def test_snapshot_rejects_a_boundary_renamed_over_an_allowed_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project"
            project.mkdir()
            package = project / "package"
            package.mkdir()
            (package / "safe.py").write_bytes(b"SAFE_SOURCE\n")
            private = project / "private"
            private.mkdir()
            (private / "secret.py").write_bytes(b"BOUNDARY_RENAME_CANARY\n")
            setup_project(project)
            register_boundary("private", "Private implementation", "private", start=project)
            config = load_config(project)
            parked = project / "package-parked"
            original_is_excluded = sources._is_excluded
            swapped = False

            def swap_after_allowed_decision(
                relative_path: str,
                name: str,
                default_excludes: frozenset[str],
                boundaries: tuple[str, ...],
            ) -> bool:
                nonlocal swapped
                excluded = original_is_excluded(
                    relative_path,
                    name,
                    default_excludes,
                    boundaries,
                )
                if relative_path == "package" and not swapped:
                    swapped = True
                    package.rename(parked)
                    private.rename(package)
                    private.mkdir()
                return excluded

            try:
                with (
                    mock.patch.object(
                        sources,
                        "_is_excluded",
                        side_effect=swap_after_allowed_decision,
                    ),
                    mock.patch.object(
                        sources,
                        "_scan_directory",
                        wraps=sources._scan_directory,
                    ) as scan_directory,
                    mock.patch.object(
                        sources,
                        "_read_regular_source",
                        wraps=sources._read_regular_source,
                    ) as read_source,
                    self.assertRaises(SourceCollectionError),
                ):
                    snapshot_sources(project, config)

                self.assertEqual(scan_directory.call_count, 1)
                read_source.assert_not_called()
            finally:
                if swapped:
                    private.rmdir()
                    package.rename(private)
                    parked.rename(package)

    @unittest.skipUnless(os.name == "nt", "Windows boundary handles are required")
    def test_snapshot_binds_boundaries_before_the_first_entry_enumeration(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project"
            project.mkdir()
            package = project / "package"
            package.mkdir()
            (package / "safe.py").write_bytes(b"SAFE_SOURCE\n")
            private = project / "private"
            private.mkdir()
            (private / "secret.py").write_bytes(b"BOUNDARY_CANARY\n")
            setup_project(project)
            register_boundary("private", "Private implementation", "private", start=project)
            config = load_config(project)
            parked = project / "package-parked"
            original_entry_ids = sources._windows_directory_entry_ids
            first_enumeration = True
            swapped = False

            def swap_before_first_enumeration(handle: int) -> dict[str, int]:
                nonlocal first_enumeration, swapped
                entry_ids = original_entry_ids(handle)
                if first_enumeration:
                    first_enumeration = False
                    package.rename(parked)
                    private.rename(package)
                    swapped = True
                return entry_ids

            try:
                with (
                    mock.patch.object(
                        sources,
                        "_windows_directory_entry_ids",
                        side_effect=swap_before_first_enumeration,
                    ),
                    mock.patch.object(
                        sources,
                        "_scan_directory",
                        wraps=sources._scan_directory,
                    ) as scan_directory,
                    mock.patch.object(
                        sources,
                        "_read_regular_source",
                        wraps=sources._read_regular_source,
                    ) as read_source,
                    self.assertRaisesRegex(SourceCollectionError, "registered boundary"),
                ):
                    snapshot_sources(project, config)

                scan_directory.assert_not_called()
                read_source.assert_not_called()
            finally:
                if swapped:
                    package.rename(private)
                    parked.rename(package)

    @unittest.skipUnless(os.name == "nt", "Windows boundary handles are required")
    def test_snapshot_rejects_a_boundary_enumeration_swap_back(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            package = project / "package"
            package.mkdir()
            (package / "safe.py").write_bytes(b"SAFE_SOURCE\n")
            private = project / "private"
            private.mkdir()
            (private / "secret.py").write_bytes(b"BOUNDARY_CANARY\n")
            setup_project(project)
            register_boundary("private", "Private implementation", "private", start=project)
            config = load_config(project)
            parked = project / "package-parked"
            original_entry_ids = sources._windows_directory_entry_ids
            first_enumeration = True

            def enumerate_during_swap(handle: int) -> dict[str, int]:
                nonlocal first_enumeration
                if not first_enumeration:
                    return original_entry_ids(handle)
                first_enumeration = False
                package.rename(parked)
                private.rename(package)
                try:
                    return original_entry_ids(handle)
                finally:
                    package.rename(private)
                    parked.rename(package)

            with (
                mock.patch.object(
                    sources,
                    "_windows_directory_entry_ids",
                    side_effect=enumerate_during_swap,
                ),
                mock.patch.object(
                    sources,
                    "_scan_directory",
                    wraps=sources._scan_directory,
                ) as scan_directory,
                mock.patch.object(
                    sources,
                    "_read_regular_source",
                    wraps=sources._read_regular_source,
                ) as read_source,
                self.assertRaisesRegex(SourceCollectionError, "registered boundary"),
            ):
                snapshot_sources(project, config)

            scan_directory.assert_not_called()
            read_source.assert_not_called()

    @unittest.skipUnless(os.name == "nt", "Windows boundary handles are required")
    def test_snapshot_binds_every_boundary_before_opening_the_first_handle(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            first = project / "boundary-a"
            first.mkdir()
            (first / "first.py").write_bytes(b"FIRST_BOUNDARY\n")
            last = project / "boundary-z"
            last.mkdir()
            (last / "last.py").write_bytes(b"LAST_BOUNDARY\n")
            package = project / "package"
            package.mkdir()
            (package / "safe.py").write_bytes(b"SAFE_SOURCE\n")
            setup_project(project)
            register_boundary("boundary-a", "First boundary", "first", start=project)
            register_boundary("boundary-z", "Last boundary", "last", start=project)
            config = load_config(project)
            parked = project / "package-parked"
            original_open = sources._open_windows_handle
            swapped = False

            def swap_last_after_first_handle(
                path: Path,
                access: int,
                flags: int,
                *,
                share: int = 0x1 | 0x2,
            ) -> int:
                nonlocal swapped
                handle = original_open(path, access, flags, share=share)
                if path == first and not swapped:
                    package.rename(parked)
                    last.rename(package)
                    parked.rename(last)
                    swapped = True
                return handle

            try:
                with (
                    mock.patch.object(
                        sources,
                        "_open_windows_handle",
                        side_effect=swap_last_after_first_handle,
                    ),
                    mock.patch.object(
                        sources,
                        "_scan_directory",
                        wraps=sources._scan_directory,
                    ) as scan_directory,
                    mock.patch.object(
                        sources,
                        "_read_regular_source",
                        wraps=sources._read_regular_source,
                    ) as read_source,
                    self.assertRaisesRegex(SourceCollectionError, "registered boundary"),
                ):
                    snapshot_sources(project, config)

                scan_directory.assert_not_called()
                read_source.assert_not_called()
            finally:
                if swapped:
                    temporary = project / "swap-restore"
                    last.rename(temporary)
                    package.rename(last)
                    temporary.rename(package)

    @unittest.skipUnless(os.name == "nt", "Windows boundary handles are required")
    def test_snapshot_binds_sibling_boundaries_in_one_parent_map(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            first = project / "boundary-a"
            first.mkdir()
            (first / "first.py").write_bytes(b"FIRST_BOUNDARY\n")
            last = project / "boundary-z"
            last.mkdir()
            (last / "last.py").write_bytes(b"LAST_BOUNDARY\n")
            package = project / "package"
            package.mkdir()
            (package / "safe.py").write_bytes(b"SAFE_SOURCE\n")
            setup_project(project)
            register_boundary("boundary-a", "First boundary", "first", start=project)
            register_boundary("boundary-z", "Last boundary", "last", start=project)
            config = load_config(project)
            parked = project / "package-parked"
            original_entry_ids = sources._windows_directory_entry_ids
            first_enumeration = True
            swapped = False

            def swap_last_after_parent_map(handle: int) -> dict[str, int]:
                nonlocal first_enumeration, swapped
                entry_ids = original_entry_ids(handle)
                if first_enumeration:
                    first_enumeration = False
                    package.rename(parked)
                    last.rename(package)
                    parked.rename(last)
                    swapped = True
                return entry_ids

            try:
                with (
                    mock.patch.object(
                        sources,
                        "_windows_directory_entry_ids",
                        side_effect=swap_last_after_parent_map,
                    ),
                    mock.patch.object(
                        sources,
                        "_scan_directory",
                        wraps=sources._scan_directory,
                    ) as scan_directory,
                    mock.patch.object(
                        sources,
                        "_read_regular_source",
                        wraps=sources._read_regular_source,
                    ) as read_source,
                    self.assertRaisesRegex(SourceCollectionError, "registered boundary"),
                ):
                    snapshot_sources(project, config)

                scan_directory.assert_not_called()
                read_source.assert_not_called()
            finally:
                if swapped:
                    temporary = project / "swap-restore"
                    last.rename(temporary)
                    package.rename(last)
                    temporary.rename(package)

    @unittest.skipUnless(os.name == "nt", "Windows boundary handles are required")
    def test_snapshot_binds_nested_boundary_ancestors_before_handles(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            private = project / "private"
            nested = private / "nested"
            nested.mkdir(parents=True)
            (nested / "secret.py").write_bytes(b"NESTED_BOUNDARY\n")
            package = project / "package"
            rival_nested = package / "nested"
            rival_nested.mkdir(parents=True)
            (rival_nested / "safe.py").write_bytes(b"SAFE_SOURCE\n")
            setup_project(project)
            register_boundary(
                "private/nested",
                "Nested boundary",
                "nested",
                start=project,
            )
            config = load_config(project)
            parked = project / "private-parked"
            original_open = sources._open_windows_handle
            swapped = False

            def swap_ancestor_before_nested_handle(
                path: Path,
                access: int,
                flags: int,
                *,
                share: int = 0x1 | 0x2,
            ) -> int:
                nonlocal swapped
                if path == nested and not swapped:
                    private.rename(parked)
                    package.rename(private)
                    parked.rename(package)
                    swapped = True
                return original_open(path, access, flags, share=share)

            try:
                with (
                    mock.patch.object(
                        sources,
                        "_open_windows_handle",
                        side_effect=swap_ancestor_before_nested_handle,
                    ),
                    mock.patch.object(
                        sources,
                        "_scan_directory",
                        wraps=sources._scan_directory,
                    ) as scan_directory,
                    mock.patch.object(
                        sources,
                        "_read_regular_source",
                        wraps=sources._read_regular_source,
                    ) as read_source,
                    self.assertRaisesRegex(SourceCollectionError, "registered boundary"),
                ):
                    snapshot_sources(project, config)

                scan_directory.assert_not_called()
                read_source.assert_not_called()
            finally:
                if swapped:
                    temporary = project / "swap-restore"
                    private.rename(temporary)
                    package.rename(private)
                    temporary.rename(package)

    @unittest.skipUnless(os.name == "nt", "Windows boundary handles are required")
    def test_snapshot_rechecks_an_ancestor_before_cross_ancestor_capture(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            first_parent = project / "ancestor-a"
            first_boundary = first_parent / "private"
            first_boundary.mkdir(parents=True)
            (first_boundary / "first.py").write_bytes(b"FIRST_BOUNDARY\n")
            last_parent = project / "ancestor-z"
            last_boundary = last_parent / "private"
            last_boundary.mkdir(parents=True)
            (last_boundary / "last.py").write_bytes(b"LAST_BOUNDARY\n")
            package = project / "package"
            package.mkdir()
            (package / "safe.py").write_bytes(b"SAFE_SOURCE\n")
            setup_project(project)
            register_boundary(
                "ancestor-a/private",
                "First nested boundary",
                "first",
                start=project,
            )
            register_boundary(
                "ancestor-z/private",
                "Last nested boundary",
                "last",
                start=project,
            )
            config = load_config(project)
            parked = project / "package-parked"
            original_entry_ids = sources._windows_directory_entry_ids
            enumerations = 0
            swapped = False

            def swap_other_ancestor_after_first_child_map(handle: int) -> dict[str, int]:
                nonlocal enumerations, swapped
                entry_ids = original_entry_ids(handle)
                enumerations += 1
                if enumerations == 2:
                    package.rename(parked)
                    last_parent.rename(package)
                    parked.rename(last_parent)
                    swapped = True
                return entry_ids

            try:
                with (
                    mock.patch.object(
                        sources,
                        "_windows_directory_entry_ids",
                        side_effect=swap_other_ancestor_after_first_child_map,
                    ),
                    mock.patch.object(
                        sources,
                        "_scan_directory",
                        wraps=sources._scan_directory,
                    ) as scan_directory,
                    mock.patch.object(
                        sources,
                        "_read_regular_source",
                        wraps=sources._read_regular_source,
                    ) as read_source,
                    self.assertRaisesRegex(SourceCollectionError, "registered boundary"),
                ):
                    snapshot_sources(project, config)

                self.assertEqual(enumerations, 2)
                scan_directory.assert_not_called()
                read_source.assert_not_called()
            finally:
                if swapped:
                    temporary = project / "swap-restore"
                    last_parent.rename(temporary)
                    package.rename(last_parent)
                    temporary.rename(package)

    @unittest.skipUnless(os.name == "nt", "Windows boundary handles are required")
    def test_snapshot_rejects_a_missing_boundary_appearing_after_parent_capture(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            package = project / "package"
            package.mkdir()
            (package / "safe.py").write_bytes(b"SAFE_SOURCE\n")
            setup_project(project)
            config = load_config(project)
            config["boundaries"].append(
                {
                    "alias": "private",
                    "description": "Missing private boundary",
                    "path": "private",
                }
            )
            private = project / "private"
            original_entry_ids = sources._windows_directory_entry_ids
            first_enumeration = True

            def create_boundary_after_parent_capture(handle: int) -> dict[str, int]:
                nonlocal first_enumeration
                entry_ids = original_entry_ids(handle)
                if first_enumeration:
                    first_enumeration = False
                    private.mkdir()
                    (private / "secret.py").write_bytes(b"BOUNDARY_CANARY\n")
                return entry_ids

            with (
                mock.patch.object(
                    sources,
                    "_windows_directory_entry_ids",
                    side_effect=create_boundary_after_parent_capture,
                ),
                mock.patch.object(
                    sources,
                    "_scan_directory",
                    wraps=sources._scan_directory,
                ) as scan_directory,
                mock.patch.object(
                    sources,
                    "_read_regular_source",
                    wraps=sources._read_regular_source,
                ) as read_source,
                self.assertRaisesRegex(SourceCollectionError, "registered boundary"),
            ):
                snapshot_sources(project, config)

            scan_directory.assert_not_called()
            read_source.assert_not_called()

    @unittest.skipUnless(os.name == "nt", "Windows boundary handles are required")
    def test_snapshot_carries_parent_map_into_the_first_traversal_map(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            package = project / "package"
            package.mkdir()
            (package / "safe.py").write_bytes(b"SAFE_SOURCE\n")
            setup_project(project)
            config = load_config(project)
            config["boundaries"].append(
                {
                    "alias": "private",
                    "description": "Missing private boundary",
                    "path": "private",
                }
            )
            private = project / "private"
            parked = project / "package-parked"
            original_entry_ids = sources._windows_directory_entry_ids
            enumerations = 0
            swapped = False

            def swap_after_final_parent_revalidation(handle: int) -> dict[str, int]:
                nonlocal enumerations, swapped
                entry_ids = original_entry_ids(handle)
                enumerations += 1
                if enumerations == 2:
                    private.mkdir()
                    (private / "secret.py").write_bytes(b"BOUNDARY_CANARY\n")
                    package.rename(parked)
                    private.rename(package)
                    swapped = True
                return entry_ids

            try:
                with (
                    mock.patch.object(
                        sources,
                        "_windows_directory_entry_ids",
                        side_effect=swap_after_final_parent_revalidation,
                    ),
                    mock.patch.object(
                        sources,
                        "_scan_directory",
                        wraps=sources._scan_directory,
                    ) as scan_directory,
                    mock.patch.object(
                        sources,
                        "_read_regular_source",
                        wraps=sources._read_regular_source,
                    ) as read_source,
                    self.assertRaisesRegex(SourceCollectionError, "registered boundary"),
                ):
                    snapshot_sources(project, config)

                self.assertEqual(enumerations, 3)
                scan_directory.assert_not_called()
                read_source.assert_not_called()
            finally:
                if swapped:
                    package.rename(private)
                    parked.rename(package)

    @unittest.skipUnless(os.name == "nt", "Windows boundary handles are required")
    def test_snapshot_rechecks_every_boundary_after_handles_are_open(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            first = project / "boundary-a"
            first.mkdir()
            (first / "first.py").write_bytes(b"FIRST_BOUNDARY\n")
            last = project / "boundary-z"
            last.mkdir()
            (last / "last.py").write_bytes(b"LAST_BOUNDARY\n")
            package = project / "package"
            package.mkdir()
            (package / "safe.py").write_bytes(b"SAFE_SOURCE\n")
            setup_project(project)
            register_boundary("boundary-a", "First boundary", "first", start=project)
            register_boundary("boundary-z", "Last boundary", "last", start=project)
            config = load_config(project)
            parked = project / "package-parked"
            original_verify = sources._verify_boundary_handle
            verified = 0
            swapped = False

            def swap_after_last_handle(*args: object, **kwargs: object) -> tuple[int, bool]:
                nonlocal verified, swapped
                entry_id = original_verify(*args, **kwargs)  # type: ignore[arg-type]
                verified += 1
                if verified == 2:
                    package.rename(parked)
                    first.rename(package)
                    parked.rename(first)
                    swapped = True
                return entry_id

            try:
                with (
                    mock.patch.object(
                        sources,
                        "_verify_boundary_handle",
                        side_effect=swap_after_last_handle,
                    ),
                    mock.patch.object(
                        sources,
                        "_scan_directory",
                        wraps=sources._scan_directory,
                    ) as scan_directory,
                    mock.patch.object(
                        sources,
                        "_read_regular_source",
                        wraps=sources._read_regular_source,
                    ) as read_source,
                    self.assertRaisesRegex(SourceCollectionError, "registered boundary"),
                ):
                    snapshot_sources(project, config)

                scan_directory.assert_not_called()
                read_source.assert_not_called()
            finally:
                if swapped:
                    temporary = project / "swap-restore"
                    first.rename(temporary)
                    package.rename(first)
                    temporary.rename(package)

    @unittest.skipUnless(os.name == "nt", "Windows boundary handles are required")
    def test_snapshot_rejects_a_boundary_swap_while_binding_its_handle(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            package = project / "package"
            package.mkdir()
            (package / "safe.py").write_bytes(b"SAFE_SOURCE\n")
            private = project / "private"
            private.mkdir()
            (private / "secret.py").write_bytes(b"BOUNDARY_CANARY\n")
            setup_project(project)
            register_boundary("private", "Private implementation", "private", start=project)
            config = load_config(project)
            parked = project / "package-parked"
            original_open = sources._open_windows_handle
            swapped = False

            def swap_before_boundary_open(
                path: Path,
                access: int,
                flags: int,
                *,
                share: int = 0x1 | 0x2,
            ) -> int:
                nonlocal swapped
                if path == private and not swapped:
                    package.rename(parked)
                    private.rename(package)
                    parked.rename(private)
                    swapped = True
                return original_open(path, access, flags, share=share)

            try:
                with (
                    mock.patch.object(
                        sources,
                        "_open_windows_handle",
                        side_effect=swap_before_boundary_open,
                    ),
                    mock.patch.object(
                        sources,
                        "_scan_directory",
                        wraps=sources._scan_directory,
                    ) as scan_directory,
                    mock.patch.object(
                        sources,
                        "_read_regular_source",
                        wraps=sources._read_regular_source,
                    ) as read_source,
                    self.assertRaisesRegex(SourceCollectionError, "registered boundary"),
                ):
                    snapshot_sources(project, config)

                scan_directory.assert_not_called()
                read_source.assert_not_called()
            finally:
                if swapped:
                    temporary = project / "swap-restore"
                    private.rename(temporary)
                    package.rename(private)
                    temporary.rename(package)

    @unittest.skipUnless(os.name == "nt", "Windows boundary handles are required")
    def test_snapshot_rejects_a_boundary_removed_before_its_handle_opens(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            package = project / "package"
            package.mkdir()
            (package / "safe.py").write_bytes(b"SAFE_SOURCE\n")
            private = project / "private"
            private.mkdir()
            (private / "secret.py").write_bytes(b"BOUNDARY_CANARY\n")
            setup_project(project)
            register_boundary("private", "Private implementation", "private", start=project)
            config = load_config(project)
            parked = project / "package-parked"
            original_open = sources._open_windows_handle
            swapped = False

            def remove_boundary_before_open(
                path: Path,
                access: int,
                flags: int,
                *,
                share: int = 0x1 | 0x2,
            ) -> int:
                nonlocal swapped
                if path == private and not swapped:
                    package.rename(parked)
                    private.rename(package)
                    swapped = True
                return original_open(path, access, flags, share=share)

            try:
                with (
                    mock.patch.object(
                        sources,
                        "_open_windows_handle",
                        side_effect=remove_boundary_before_open,
                    ),
                    mock.patch.object(
                        sources,
                        "_scan_directory",
                        wraps=sources._scan_directory,
                    ) as scan_directory,
                    mock.patch.object(
                        sources,
                        "_read_regular_source",
                        wraps=sources._read_regular_source,
                    ) as read_source,
                    self.assertRaisesRegex(SourceCollectionError, "registered boundary"),
                ):
                    snapshot_sources(project, config)

                scan_directory.assert_not_called()
                read_source.assert_not_called()
            finally:
                if swapped:
                    package.rename(private)
                    parked.rename(package)

    @unittest.skipUnless(os.name == "nt", "Windows file IDs are required")
    def test_snapshot_rejects_a_hard_link_to_a_boundary_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            private = project / "private.py"
            private.write_bytes(b"BOUNDARY_CANARY\n")
            setup_project(project)
            register_boundary("private.py", "Private source", "private", start=project)
            config = load_config(project)
            os.link(private, project / "public.py")

            with (
                mock.patch.object(
                    sources,
                    "_read_regular_source",
                    wraps=sources._read_regular_source,
                ) as read_source,
                self.assertRaisesRegex(SourceCollectionError, "registered boundary"),
            ):
                snapshot_sources(project, config)

            read_source.assert_not_called()

    @unittest.skipUnless(os.name == "nt", "Windows handles are required")
    def test_windows_entry_enumeration_does_not_leak_handles(self) -> None:
        import ctypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.GetCurrentProcess.restype = ctypes.c_void_p
        kernel32.GetProcessHandleCount.argtypes = (
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_uint32),
        )
        kernel32.GetProcessHandleCount.restype = ctypes.c_int

        def handle_count() -> int:
            count = ctypes.c_uint32()
            if not kernel32.GetProcessHandleCount(
                kernel32.GetCurrentProcess(), ctypes.byref(count)
            ):
                raise ctypes.WinError(ctypes.get_last_error())
            return int(count.value)

        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            package = project / "package"
            package.mkdir()
            (package / "module.py").write_bytes(b"VALUE = 1\n")
            private = project / "private"
            private.mkdir()
            (private / "secret.py").write_bytes(b"BOUNDARY_CANARY\n")
            setup_project(project)
            register_boundary("private", "Private implementation", "private", start=project)
            config = load_config(project)
            before = handle_count()

            for _ in range(50):
                snapshot_sources(project, config)

            self.assertEqual(handle_count(), before)

    def test_windows_extended_paths_are_not_prefixed_twice(self) -> None:
        drive_path = Path(r"\\?\C:\project\source.py")
        unc_path = Path(r"\\?\UNC\server\share\source.py")

        self.assertEqual(sources._windows_extended_path(drive_path), str(drive_path))
        self.assertEqual(sources._windows_extended_path(unc_path), str(unc_path))

    @unittest.skipUnless(os.name == "nt", "Windows extended paths are required")
    def test_snapshot_accepts_an_extended_drive_project_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            private = project / "private"
            private.mkdir()
            (private / "secret.py").write_bytes(b"BOUNDARY_CANARY\n")
            (project / "visible.py").write_bytes(b"VISIBLE\n")
            setup_project(project)
            register_boundary("private", "Private implementation", "private", start=project)
            config = load_config(project)
            extended_project = Path(f"\\\\?\\{project}")

            snapshot = snapshot_sources(extended_project, config)

            self.assertEqual([source.path for source in snapshot.files], ["visible.py"])

    @unittest.skipUnless(os.name == "nt", "Windows UNC paths are required")
    def test_snapshot_accepts_an_extended_unc_project_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            private = project / "private"
            private.mkdir()
            (private / "secret.py").write_bytes(b"BOUNDARY_CANARY\n")
            (project / "visible.py").write_bytes(b"VISIBLE\n")
            setup_project(project)
            register_boundary("private", "Private implementation", "private", start=project)
            config = load_config(project)
            drive = project.drive.removesuffix(":")
            relative = str(project)[len(project.anchor) :]
            unc_project = Path(f"\\\\localhost\\{drive}$\\{relative}")
            if not drive or not unc_project.is_dir():
                self.skipTest("the local administrative share is unavailable")
            extended_project = Path(f"\\\\?\\UNC\\{str(unc_project)[2:]}")

            snapshot = snapshot_sources(extended_project, config)

            self.assertEqual([source.path for source in snapshot.files], ["visible.py"])

    def test_snapshot_rejects_root_changed_to_a_directory_link_before_open(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project"
            project.mkdir()
            (project / "local.py").write_bytes(b"LOCAL\n")
            outside = root / "outside"
            outside.mkdir()
            (outside / "secret.py").write_bytes(b"ROOT_SWAP_CANARY\n")
            setup_project(project)
            config = load_config(project)
            swap = ExitStack()
            swapped = False

            def swap_after_component_check(path: Path) -> bool:
                nonlocal swapped
                if not swapped:
                    swapped = True
                    swap.enter_context(swapped_directory(project, outside))
                return False

            try:
                with (
                    mock.patch(
                        "silobrief.sources.has_link_like_component",
                        side_effect=swap_after_component_check,
                    ),
                    self.assertRaises(SourceCollectionError),
                ):
                    snapshot_sources(project, config)
            finally:
                swap.close()

    def test_snapshot_rejects_a_real_root_replacement_after_loading_config(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            project = workspace / "project"
            project.mkdir()
            (project / "local.py").write_bytes(b"LOCAL\n")
            setup_project(project)
            config, identity = load_source_config(project)

            replacement = workspace / "replacement"
            replacement.mkdir()
            (replacement / "secret.py").write_bytes(b"REAL_ROOT_SWAP_CANARY\n")
            setup_project(replacement)

            with (
                swapped_real_directory(project, replacement),
                mock.patch(
                    "silobrief.sources._read_regular_source",
                    wraps=sources._read_regular_source,
                ) as read_source,
                self.assertRaisesRegex(SourceCollectionError, "project root changed"),
            ):
                snapshot_sources(
                    project,
                    config,
                    expected_root_identity=identity,
                )

            self.assertFalse(read_source.called)

    @unittest.skipIf(os.name == "nt", "POSIX source roots use a protected directory FD")
    def test_config_is_loaded_from_the_protected_posix_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            project = workspace / "project"
            project.mkdir()
            setup_project(project)

            replacement = workspace / "replacement"
            replacement.mkdir()
            setup_project(replacement)
            register_boundary(
                ".",
                "Replacement-only boundary",
                "replacement-only",
                start=replacement,
            )
            original_load = load_config
            loaded_config: ConfigData | None = None

            def load_during_swap(path: Path) -> ConfigData:
                nonlocal loaded_config
                with swapped_real_directory(project, replacement):
                    loaded_config = original_load(path)
                    return loaded_config

            with mock.patch("silobrief.sources.load_config", side_effect=load_during_swap):
                with self.assertRaises(SourceCollectionError):
                    load_source_config(project)

            self.assertIsNotNone(loaded_config)
            self.assertEqual(cast(ConfigData, loaded_config)["boundaries"], [])

    def test_snapshot_cannot_swap_a_scanned_ancestor_into_a_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project"
            project.mkdir()
            package = project / "package"
            package.mkdir()
            (package / "secret.py").write_bytes(b"SAFE_SOURCE\n")
            private = project / "private"
            private.mkdir()
            (private / "secret.py").write_bytes(b"BOUNDARY_SWAP_CANARY\n")
            setup_project(project)
            register_boundary("private", "Private implementation", "private", start=project)
            config = load_config(project)
            original_read = sources._read_regular_source
            original_scan = os.scandir
            package_inode = package.stat().st_ino

            @contextmanager
            def scan_with_swap(
                target: int | str | os.PathLike[str],
            ) -> Iterator[Iterator[os.DirEntry[str]]]:
                is_package = (
                    Path(target) == package
                    if not isinstance(target, int)
                    else os.fstat(target).st_ino == package_inode
                )
                if is_package:
                    with swapped_directory(package, private), original_scan(target) as iterator:
                        yield iterator
                    return
                with original_scan(target) as iterator:
                    yield iterator

            def swap_before_read(*args: object, **kwargs: object) -> sources.SourceFile:
                relative_path = cast(str, args[1])
                if relative_path != "package/secret.py":
                    return original_read(*args, **kwargs)  # type: ignore[arg-type]
                with swapped_directory(package, private):
                    return original_read(*args, **kwargs)  # type: ignore[arg-type]

            with (
                mock.patch("silobrief.sources.os.scandir", side_effect=scan_with_swap),
                mock.patch("silobrief.sources._read_regular_source", side_effect=swap_before_read),
            ):
                with self.assertRaises(SourceCollectionError):
                    snapshot_sources(project, config)

    @unittest.skipIf(os.name == "nt", "/proc descriptor paths are used on Ubuntu")
    def test_snapshot_fails_closed_when_descriptor_path_is_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            (project / "module.py").write_bytes(b"VALUE = 1\n")
            setup_project(project)
            config = load_config(project)

            with (
                mock.patch(
                    "silobrief.sources.os.readlink",
                    side_effect=OSError("descriptor path unavailable"),
                ),
                self.assertRaises(SourceCollectionError),
            ):
                snapshot_sources(project, config)


if __name__ == "__main__":
    unittest.main()
