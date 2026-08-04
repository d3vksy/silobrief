# siloBrief v0.2 installed-wheel verification

Status: `SUPERSEDED`

This record applies to the packet format before Issue #75 simplified the AI-facing brief. It is
retained as historical evidence only; the current model inputs and hashes are frozen in
`MANUAL_MODEL_GATE.md` and checked against the current CLI by `tests/test_model_validation.py`.

Verified at 2026-08-05 (Asia/Seoul), before any GPT or Claude trial.

## Build identity

- source commit: `8b29934fe1ee144443600cf8a9a9675fc86ad981`
- package metadata version: `0.1.0`
- wheel: `silobrief-0.1.0-py3-none-any.whl`
- wheel SHA-256:
  `dc77f27ac740edfcac8c825e8e343e9e08a86abdcd27cfc4d5d4ad8250bcc037`
- CI run: <https://github.com/d3vksy/silobrief/actions/runs/30926093793>

The version remains `0.1.0` because the frozen manual model gate must pass before a v0.2 version
bump. The verification record changes no package source or frozen packet bytes.

## Windows result

- OS: Microsoft Windows NT 10.0.26200.0
- Python: 3.14.3
- install: new venv, local wheel, `pip --no-index --no-deps`
- interactive host: Windows ConPTY with stdin, stdout, and stderr all reporting `isatty() == True`
- installed command: `windows-venv\Scripts\sb.exe`
- flow: `setup → ignore → init → log → chat` for T01, T02, and T03
- result: all three paired outputs completed with exact `WRITE`; T01 also required exact `EXPOSE`
- source comparison: byte-identical before and after, excluding generated `.silobrief/`
- packet comparison: all six files byte-identical to the frozen packet set

The ConPTY host was a temporary verification runner outside the product. It did not patch Python,
siloBrief, `isatty()`, approval input, or generated files.

## Ubuntu result

- environment: Ubuntu on WSL2, Linux kernel 6.6.87.2-microsoft-standard-WSL2, x86_64
- Python: 3.12.3
- pip: 24.0
- install: isolated target directory, local wheel, `pip --target --no-index --no-deps`
- interactive host: `/usr/bin/script` native pseudo-terminal
- installed command: pip-generated `site/bin/sb` with only the isolated site on `PYTHONPATH`
- flow: `setup → ignore → init → log → chat` for T01, T02, and T03
- result: all three paired outputs completed with exact `WRITE`; T01 also required exact `EXPOSE`
- source comparison: byte-identical before and after, excluding generated `.silobrief/`
- packet comparison: all six files byte-identical to the frozen packet set

Ubuntu `ensurepip` was unavailable, so a venv could not be created without installing an OS
package. The isolated `pip --target` directory was used instead; no system package or system Python
file was changed.

## Reproduced packet SHA-256

Both environments produced these values:

| File | SHA-256 |
|---|---|
| `T01-MODIFY/t01-modify.md` | `0ef829e88a240c29ec62b0281015abec48b6f1b7476ada412059cdfef140dd30` |
| `T01-MODIFY/t01-modify.sources.md` | `26e81597f2edd4c65f226ddafc4a291e595e5fb75f5a133d5136ca94d106e698` |
| `T02-ADD/t02-add.md` | `55bee4ae3e5e34f3570c908d88227d8c181b497db916def96669552b6826c744` |
| `T02-ADD/t02-add.sources.md` | `7deb0e384fbf625f295ade605d6cb1da2d2bc4a9c68ebe83c6fb4e46b4ed6574` |
| `T03-REMOVE/t03-remove.md` | `75fb9d63c0023a3afee3132b2740b308db9ed5cf68cea5087ea890630acb83ce` |
| `T03-REMOVE/t03-remove.sources.md` | `4ad9d025d2027cc569499a0d42cbdaf6b0b650c5cc6cce09c0bbe74c0aa9c597` |

## Network and scope

- The wheel was built locally with `--no-isolation`.
- Both installations used `--no-index --no-deps`; no package download was requested.
- siloBrief itself has no network path, and the full test suite blocks socket connection attempts
  during model packet generation.
- GitHub CI passed Ubuntu and Windows on Python 3.10 and 3.14, including wheel/sdist build and
  installed `sb --version` smoke tests.
- No GPT or Claude chat was opened, no response was collected, and no packet or threshold was
  changed during this verification.

The next action is the six fresh-chat trials described in `MANUAL_MODEL_GATE.md`. Only each task's
two frozen packet files are model inputs.
