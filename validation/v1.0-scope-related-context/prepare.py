from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

import frozen_evaluator

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
CORPUS_ROOT = HERE / "corpus"


class PreparationError(RuntimeError):
    pass


def git_environment() -> dict[str, str]:
    environment = os.environ.copy()
    for name in tuple(environment):
        if name.startswith("GIT_"):
            environment.pop(name)
    environment.update(
        {
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_NO_REPLACE_OBJECTS": "1",
            "GIT_OPTIONAL_LOCKS": "0",
        }
    )
    return environment


def run_git(
    project: Path,
    *arguments: str,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        (
            "git",
            "--no-replace-objects",
            "--no-optional-locks",
            "-c",
            f"safe.directory={project.as_posix()}",
            "-c",
            "core.fsmonitor=false",
            "-c",
            "core.untrackedCache=false",
            "-c",
            "core.longpaths=true",
            *arguments,
        ),
        cwd=project,
        env=git_environment(),
        check=False,
        capture_output=True,
        text=True,
    )
    if check and completed.returncode != 0:
        reason = completed.stderr.strip() or completed.stdout.strip() or "Git returned no details"
        raise PreparationError(f"Git failed in {project}: {reason}")
    return completed


def git_output(project: Path, *arguments: str) -> str:
    return run_git(project, *arguments).stdout.strip()


def has_commit(project: Path, commit: str) -> bool:
    return run_git(project, "cat-file", "-e", f"{commit}^{{commit}}", check=False).returncode == 0


def require_clean(project: Path) -> None:
    status = git_output(project, "status", "--porcelain=v1", "--untracked-files=all")
    if status:
        raise PreparationError(
            f"refusing to update a checkout with local changes: {project}\n{status}"
        )


def fetch_commit(project: Path, commit: str) -> None:
    run_git(project, "fetch", "--quiet", "--no-tags", "--depth=1", "origin", commit)
    resolved = git_output(project, "rev-parse", f"{commit}^{{commit}}")
    if resolved != commit:
        raise PreparationError(f"fetched commit did not resolve exactly: {commit}")


def enable_long_paths(project: Path) -> None:
    current = run_git(project, "config", "--local", "--get", "core.longpaths", check=False)
    if current.returncode != 0 or current.stdout.strip().casefold() != "true":
        run_git(project, "config", "--local", "core.longpaths", "true")


def prepare_repository(url: str, commit: str, target: Path) -> str:
    if target.exists():
        if not target.is_dir() or not (target / ".git").exists():
            raise PreparationError(f"checkout path exists but is not a Git repository: {target}")
        remote = git_output(target, "remote", "get-url", "origin")
        if remote != url:
            raise PreparationError(
                f"origin URL differs for {target}\nexpected: {url}\nactual:   {remote}"
            )
        require_clean(target)
        enable_long_paths(target)
        if not has_commit(target, commit):
            fetch_commit(target, commit)
        head = git_output(target, "rev-parse", "HEAD")
        attached = run_git(target, "symbolic-ref", "-q", "HEAD", check=False).returncode == 0
        if head != commit or attached:
            run_git(target, "checkout", "--quiet", "--detach", commit)
        require_clean(target)
        return "reused"

    target.parent.mkdir(parents=True, exist_ok=True)
    target.mkdir()
    try:
        run_git(target, "init", "--quiet", ".")
        enable_long_paths(target)
        run_git(target, "remote", "add", "origin", url)
        fetch_commit(target, commit)
        run_git(target, "checkout", "--quiet", "--detach", commit)
        require_clean(target)
    except BaseException as error:
        shutil.rmtree(target, ignore_errors=True)
        if target.exists():
            raise PreparationError(
                f"{error}\npartial checkout remains at {target}; remove it and retry"
            ) from error
        raise
    return "created"


def copy_manifests(external_root: Path) -> None:
    for _suite, directory, expected_digest in frozen_evaluator.MANIFESTS:
        source = CORPUS_ROOT / directory / "holdout.json"
        content = source.read_bytes()
        if frozen_evaluator.sha256(content) != expected_digest:
            raise PreparationError(f"tracked manifest digest changed: {source}")
        destination = external_root / directory / "holdout.json"
        if destination.resolve() == source.resolve():
            continue
        if destination.exists():
            if (
                not destination.is_file()
                or frozen_evaluator.sha256(destination.read_bytes()) != expected_digest
            ):
                raise PreparationError(f"refusing to replace a different manifest: {destination}")
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)


def repositories(external_root: Path) -> tuple[tuple[str, str, Path], ...]:
    cases = frozen_evaluator.load_manifests(external_root)
    result: list[tuple[str, str, Path]] = []
    seen: set[Path] = set()
    for case in cases:
        repository = str(case["repository"])
        target = Path(str(case["root"])) / repository.rsplit("/", 1)[-1]
        if target in seen:
            raise PreparationError(f"duplicate checkout path in manifests: {target}")
        seen.add(target)
        result.append((f"https://github.com/{repository}.git", str(case["commit"]), target))
    return tuple(result)


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        description="Prepare the 12 pinned repositories used by the scope evaluator."
    )
    result.add_argument(
        "--external-root",
        type=Path,
        default=CORPUS_ROOT,
        help="manifest and checkout root (default: repository-local corpus)",
    )
    return result


def run(external_root: Path) -> None:
    if shutil.which("git") is None:
        raise PreparationError("Git is required to prepare the scope evaluation corpus")
    external_root = external_root.resolve()
    copy_manifests(external_root)
    specs = repositories(external_root)
    for position, (url, commit, target) in enumerate(specs, start=1):
        state = prepare_repository(url, commit, target)
        repository = url.removeprefix("https://github.com/").removesuffix(".git")
        print(f"[{position}/{len(specs)}] {state} {repository} at {commit}")
    print(f"scope corpus ready under {external_root}")


def main() -> int:
    arguments = parser().parse_args()
    try:
        run(arguments.external_root)
    except (OSError, PreparationError) as error:
        print(f"scope corpus preparation failed: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
