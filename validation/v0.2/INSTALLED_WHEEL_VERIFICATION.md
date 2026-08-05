# siloBrief v0.2 installed-wheel verification

Status: `PASS FOR v0.2.0 RELEASE CANDIDATE`

Verified: 2026-08-05 (Asia/Seoul)

## Build identity

- functional source base: `84747f3d2be6243f56a09d94998cdd1c54fbdc4b`
- package metadata version: `0.2.0`
- wheel: `silobrief-0.2.0-py3-none-any.whl`
- tested wheel SHA-256:
  `0d74eaabe402c2f6d00a85bca590017d91b3e4899c1d31daa247ed86c1485de5`
- revision 3 CI run: <https://github.com/d3vksy/silobrief/actions/runs/30967246484>

The release-candidate changes after the functional source base are version, release documentation,
validation evidence, and their tests. No product source under `src/silobrief/` changed.

## Windows result

- OS: Microsoft Windows NT 10.0.26200.0
- Python: 3.14.3
- install: new venv, local wheel, `pip --no-index --no-deps`
- installed command: `venv\Scripts\sb.exe`
- `sb --version`: `siloBrief 0.2.0`
- E2E harness: installed package generated T01, T02, and T03 main/source pairs
- packet comparison: all six files byte-identical to revision 3
- source comparison: byte-identical before and after, excluding `.silobrief/`

## Ubuntu result

- environment: Ubuntu on WSL2, x86_64
- Python: 3.12.3
- install: isolated target directory, the same local wheel, `pip --no-index --no-deps`
- installed command: isolated `site/bin/sb`
- `sb --version`: `siloBrief 0.2.0`
- E2E harness: installed package generated T01, T02, and T03 main/source pairs
- packet comparison: all six files byte-identical to revision 3
- source comparison: byte-identical before and after, excluding `.silobrief/`

Ubuntu's system setuptools was older than the declared `setuptools>=77` build requirement, so it
was not used to build the package. The platform-independent wheel built in the supported Windows
build environment was installed directly, which matches the intended wheel installation path.

## Reproduced packet SHA-256

Both environments produced these values:

| File | SHA-256 |
|---|---|
| `T01-MODIFY/t01-modify.md` | `799c083b0df08b8a62af1d6e0078fded210757acd288d8872b918136d7fed4c3` |
| `T01-MODIFY/t01-modify.sources.md` | `26e81597f2edd4c65f226ddafc4a291e595e5fb75f5a133d5136ca94d106e698` |
| `T02-ADD/t02-add.md` | `1a4047204b5d474acad6572cb15c906aea1295242bdeaa10cc8abe46793da11b` |
| `T02-ADD/t02-add.sources.md` | `7deb0e384fbf625f295ade605d6cb1da2d2bc4a9c68ebe83c6fb4e46b4ed6574` |
| `T03-REMOVE/t03-remove.md` | `de1df5fd18c72840f401229e7fc6f25016ecfaa70ac5bd643ecf59c22fee8311` |
| `T03-REMOVE/t03-remove.sources.md` | `4ad9d025d2027cc569499a0d42cbdaf6b0b650c5cc6cce09c0bbe74c0aa9c597` |

## Network and scope

- The tested wheel was built locally with `--no-isolation`.
- Both installations used `--no-index --no-deps`; no package download was requested.
- Packet generation blocked socket connection attempts.
- CI passed Ubuntu and Windows on Python 3.10 and 3.14 for revision 3, including wheel/sdist build,
  wheel installation, the full test suite, and `sb --version`.
- Claude manual results are recorded separately. GPT validation is deferred and cross-model
  effectiveness is not claimed.
