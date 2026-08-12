# v1.0.1 release verification

Date: 2026-08-12

Status: PASS for the tagged source, release artifacts, publishing provenance, and frozen retrieval
benchmark described below.

## Scope

This record verifies the public `v1.0.1` tag and the exact wheel and sdist produced by the successful
PyPI publishing workflow. Later changes on `main` are outside this record. This is release and
repository verification, not a user field trial or evidence of market demand.

## Source and publishing provenance

The annotated `v1.0.1` tag resolves to commit
`74e213c3867fff437c9ac5909a77264b07865fbc`. The successful
[PyPI publishing run](https://github.com/d3vksy/silobrief/actions/runs/31545145103) reports the same
`head_sha`, and the tag commit is reachable from `main`.

The publishing workflow checked out `refs/tags/v1.0.1`, compared the tag commit with `HEAD`, checked
that the commit was reachable from `main`, verified the version in `pyproject.toml`, ran the release
tests, built exactly one wheel and one sdist, and uploaded those files as artifact `pypi-1.0.1`.
The publish job downloaded that validated artifact and sent it to PyPI through Trusted Publishing.

The separate [CI run](https://github.com/d3vksy/silobrief/actions/runs/31545007156) for the same commit
passed the Ubuntu and Windows matrix on Python 3.10 and 3.14. Each matrix job ran Ruff, formatting,
mypy strict checks, the test suite, distribution builds, wheel installation, and the installed-wheel
test suite.

The annotated tag is not cryptographically signed. The exact tag, workflow SHA, artifact hashes,
and release files remain independently comparable.

## Artifact identity

The GitHub Release files and the expiring `pypi-1.0.1` workflow artifact were downloaded separately
on 2026-08-12 and compared byte for byte by SHA-256.

| Artifact | SHA-256 | Release/workflow match |
|---|---|---|
| `silobrief-1.0.1-py3-none-any.whl` | `8e41170563821434b82d3cbf75218e144228b19dbdab86570cd0ebf5873f1784` | yes |
| `silobrief-1.0.1.tar.gz` | `b7554e16b29a68856a366ded3efcda138237f4246967d673e8e916a44cfd8669` | yes |

All 30 hashed entries in the wheel's `RECORD` file matched their archived bytes and declared sizes.

## Local source-tree checks

The following checks passed on Windows with CPython 3.14.3:

```powershell
python -m ruff check .
python -m mypy src tests
python -m unittest discover -s tests -q
```

Ruff reported no findings, mypy strict mode reported no issues in 54 source files, and all 179 tests
passed with 7 environment-dependent skips.

## Frozen retrieval benchmark

The production indexer and ranking implementation were rerun through
`tests/test_graph_retrieval_baseline.py` at `v1.0.1` behavior. The current result is:

| Metric | Result |
|---|---:|
| Fixed maintenance tasks | 12 |
| Tasks with an expected symbol in returned candidates | 11/12 |
| Expected symbols returned | 14/17 |
| Expected symbols reachable within two graph hops | 17/17 |
| Mean reciprocal rank | 72.2% (`13/18`) |
| Irrelevant returned candidates | 41 |
| Maximum expanded nodes for one task | 10 |
| Registered-boundary canary disclosures | 0 |

Reproduction:

```powershell
$env:PYTHONPATH='src'
python -m unittest tests.test_graph_retrieval_baseline -v
python tests/test_graph_retrieval_baseline.py
```

The second command prints canonical JSON. For this source tree, including a final newline, its
SHA-256 is `6109a3a0d8995e81c27cd172bcb7d84faf7c2b2fcb067006e3b0d6e6cc6638f3`.

## Interpretation and limits

The earlier `validation/v0.7/RETRIEVAL_RESULT.md` remains an immutable historical result. Its
44 irrelevant candidates and pending hosted-CI note describe that revision, while this document
records the v1.0.1 state.

The benchmark is small and includes repository-local and synthetic tasks. It demonstrates stable
behavior against declared gates, not superiority to manual selection or other tools. It does not
establish broad user demand, automatic context completeness, secret detection, export approval, or
improved answers from external AI models. Candidate search remains lexical and advisory.

The static Python graph also does not promise complete language semantics. Dynamic imports,
reflection, wildcard-import binding, package re-export chains, and aliases created by assignment may
remain unresolved. Exact-path selection and human review remain the supported fallback.
