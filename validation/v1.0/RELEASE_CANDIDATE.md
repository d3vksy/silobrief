# 1.0.0rc1 verification

Date: 2026-08-11

Historical scope: this record captures the pre-approval `1.0.0rc1` freeze. The owner approved the
final `1.0.0` GitHub and PyPI release later on 2026-08-11; final publication uses separately rebuilt
`1.0.0` artifacts.

Status: local release candidate passed; owner approval, Git tag, GitHub release, and package
publication have not occurred.

## Source-tree checks

```powershell
python -m ruff check .
python -m ruff format --check .
python -m mypy
python -m unittest discover -s tests -q
git diff --check
```

Result on Windows: PASS. The suite ran 177 tests with 7 environment-dependent skips. Strict typing
reported no issues in 54 source files, lint passed, and all 66 Python files matched the formatter.

The final sdist was also extracted outside the repository and tested with WSL2 Ubuntu and Python
3.12.3. All 174 runtime tests passed. The three packaging tests were not run there because that WSL
installation lacks `python3-venv`, `build`, Ruff, and mypy; the clean Windows build/install checks
below cover packaging. Windows and Ubuntu produced identical canonical retrieval-benchmark JSON
with SHA-256 `08b4f3816ebe535de5e7931e7904b2612237827ed968cd4c88ae8534019f1314`.

## GitHub issue #42: `sb init` progress

The release candidate includes the post-v0.1 progress request as a bounded usability fix. A local
three-run timing sample separated the existing work before implementation:

| Sample | Python files | collect | analyze | build + render | verify |
|---|---:|---:|---:|---:|---:|
| repository source/test copy | 54 | 0.2715 s | 0.0769 s | 0.1970 s | 0.0070 s |
| synthetic small modules | 1,000 | 0.3182 s | 0.0231 s | 0.1358 s | 0.0938 s |

Because collection and index construction were at least as material as AST analysis in these
samples, the UI reports five real phases instead of presenting a misleading file-only percentage:
collect, analyze, build, verify source stability, and write. The bar uses only standard-library
terminal output and does not add a worker thread, parallel indexing, or a runtime dependency.

Automated TTY simulation verifies the 0% through 100% phase display and clean line termination on
failure. A paired non-TTY run verifies zero progress output, unchanged exit behavior, and
byte-identical `index.json` output for the same source. The GitHub issue remains open until owner
approval and release handling.

## Built artifacts

Built with `python -m build --no-isolation` from the release-candidate worktree.

The final local wheel digest is recorded below after the source and package metadata freeze. The
sdist is built after this record so that it contains the record itself; its digest is reported at
handoff rather than embedded recursively inside the archive.

| Artifact | SHA-256 |
|---|---|
| `silobrief-1.0.0rc1-py3-none-any.whl` | `cad40e52b79e4ddbf22e2187604ca198222b888c7523b87240938b7bc7322753` |

## Clean-wheel smoke test

The wheel was installed with `--no-deps` into a newly created virtual environment outside the
repository. The following checks passed using only the installed artifact:

- `sb --version` returned `siloBrief 1.0.0rc1`;
- `sb --help` listed `brief` and the deprecated `chat` alias;
- `python -m pip check` reported no broken requirements;
- `sb example`, `sb setup`, `sb init`, and `sb search` completed on the generated project;
- captured non-TTY `sb init` wrote zero progress bytes to standard error;
- search returned the expected `format_label` symbol.

Interactive `sb brief` behavior is covered by the source-tree TTY simulation and end-to-end tests,
including default-no related context, source preview, `EXPOSE`, full preview, and exact `WRITE`.

## PyPI publishing workflow

`.github/workflows/publish-pypi.yml` provides one manual `version` input. The build job accepts a
strict release version without a `v` prefix, checks out the matching `vVERSION` tag, requires that
tag to be reachable from `main`, and verifies the source and distribution metadata before storing
the artifacts. A separate `pypi` environment job receives only `id-token: write`, downloads those
artifacts, and publishes them with PyPI Trusted Publishing. No long-lived PyPI token is configured.

The workflow YAML parses successfully, every referenced action is pinned to a full commit SHA, and
the embedded request, tag, metadata, and artifact checks passed both positive and negative local
simulations. The actual workflow cannot run until it is present on the default branch. The live
repository currently has no `pypi` environment or tag ruleset, and the `silobrief` PyPI project is
not yet registered. `CONTRIBUTING.md` records the one-time GitHub environment and pending Trusted
Publisher setup that must precede the first approved publication.

## Approval boundary

Before a public 1.0.0 release:

1. review the worktree diff and known limitations;
2. optionally run the solo field-trial procedure;
3. obtain explicit owner approval;
4. only then change `1.0.0rc1` to `1.0.0`, rebuild and reverify artifacts, commit, tag, push, create
   a GitHub release, configure the documented Trusted Publisher prerequisites, and manually run
   the PyPI workflow with version `1.0.0` as authorized.
