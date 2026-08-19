from __future__ import annotations

import argparse
import sys
from pathlib import Path

import frozen_evaluator

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
CORPUS_ROOT = HERE / "corpus"
PREPARE_PATH = HERE / "prepare.py"


class InputError(RuntimeError):
    pass


def prepare_command(external_root: Path) -> str:
    command = f"python {PREPARE_PATH.relative_to(ROOT).as_posix()}"
    if external_root != CORPUS_ROOT.resolve():
        command += f' --external-root "{external_root}"'
    return command


def evaluation_root(external_root: Path) -> Path:
    if sys.platform != "win32":
        return external_root
    value = str(external_root)
    if value.startswith("\\\\?\\"):
        return external_root
    if value.startswith("\\\\"):
        return Path(f"\\\\?\\UNC\\{value[2:]}")
    return Path(f"\\\\?\\{value}")


def validate_inputs(external_root: Path) -> None:
    missing_manifests = [
        external_root / directory / "holdout.json"
        for _suite, directory, _digest in frozen_evaluator.MANIFESTS
        if not (external_root / directory / "holdout.json").is_file()
    ]
    if missing_manifests:
        paths = "\n".join(f"  - {path}" for path in missing_manifests)
        raise InputError(
            "scope evaluation manifests are missing:\n"
            f"{paths}\n"
            "Prepare the pinned corpus from the repository root:\n"
            f"  {prepare_command(external_root)}"
        )

    try:
        cases = frozen_evaluator.load_manifests(external_root)
    except (OSError, RuntimeError, ValueError) as error:
        raise InputError(
            f"scope evaluation manifest check failed under {external_root}: {error}\n"
            "Restore the tracked manifests from a clean clone before continuing."
        ) from error

    missing_projects = [
        path
        for path in frozen_evaluator.external_projects(cases).values()
        if not path.is_dir() or not (path / ".git").exists()
    ]
    if missing_projects:
        paths = "\n".join(f"  - {path}" for path in missing_projects)
        raise InputError(
            "pinned scope evaluation checkouts are missing:\n"
            f"{paths}\n"
            "Prepare them from the repository root:\n"
            f"  {prepare_command(external_root)}"
        )


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        description="Recompute the frozen scope-related context study."
    )
    result.add_argument("--check", action="store_true")
    result.add_argument(
        "--external-root",
        type=Path,
        default=CORPUS_ROOT,
        help="manifest and checkout root (default: repository-local corpus)",
    )
    result.add_argument("--worker", choices=("baseline", "current"), help=argparse.SUPPRESS)
    return result


def run(arguments: argparse.Namespace) -> int:
    external_root = arguments.external_root.resolve()
    validate_inputs(external_root)
    worker_root = evaluation_root(external_root)
    if arguments.worker is not None:
        sys.stdout.buffer.write(frozen_evaluator.run_worker(arguments.worker, worker_root))
        return 0

    rendered = frozen_evaluator.evaluate(worker_root)
    if arguments.check:
        if (
            not frozen_evaluator.RESULT_PATH.is_file()
            or frozen_evaluator.RESULT_PATH.read_bytes() != rendered
        ):
            raise RuntimeError("canonical result differs; run evaluator without --check")
        print(f"canonical_sha256={frozen_evaluator.sha256(rendered)}")
        return 0

    frozen_evaluator.RESULT_PATH.write_bytes(rendered)
    relative = frozen_evaluator.RESULT_PATH.relative_to(ROOT)
    print(f"wrote {relative} sha256={frozen_evaluator.sha256(rendered)}")
    return 0


def main() -> int:
    arguments = parser().parse_args()
    try:
        return run(arguments)
    except InputError as error:
        print(f"scope evaluator: error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
