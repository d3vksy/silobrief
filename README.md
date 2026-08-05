# siloBrief

[한국어](README.ko.md)

siloBrief is a local command-line tool that turns reviewed Python project context into a
Markdown brief and, when explicitly approved, a companion containing selected source excerpts.
It is intended for development environments where source code and internet access are separated.

The current release is v0.2.0. Its behavior is documented in
[`docs/V0_2_CONTRACT.md`](docs/V0_2_CONTRACT.md). Claude passed all three synthetic maintenance
tasks; GPT validation remains follow-up work and cross-model effectiveness is not established.

## Requirements and installation

- Python 3.10 or newer
- Windows or Ubuntu
- no runtime dependencies

Install the current checkout and verify the command:

```console
python -m pip install .
sb --version
```

Expected output:

```text
siloBrief 0.2.0
```

## Quick start

Use a disposable copy of the synthetic
[`parcel-sync-fixture`](examples/parcel-sync-fixture/README.md). From its root, run:

```console
sb setup .
sb ignore private_adapter --as "External delivery adapter" --alias delivery-boundary
sb init
sb log src/parcel_sync/service.py --comment "HTTP 503 responses may be retried."
sb chat "retry request" --out .silobrief/exports/retry-brief.md
```

For this fixture, confirm the request with `y`, select candidate `1`, submit blank add and exclude
prompts, and approve the five context field groups. The selected function is then shown in full.
Answer `y` only after reviewing it, type `EXPOSE` to approve the visible boundary identifier, and
inspect both complete previews. Exact `WRITE` creates `retry-brief.md` and
`retry-brief.sources.md`. Declining the source excerpt creates only the main brief.

## Writing useful input

Write `PROMPT` as a concrete task rather than a few keywords. Include the required deliverables
and acceptance criteria so the recipient can tell what a useful answer must contain.

Use `sb log` only for context that project structure cannot show. Record only context that you
have approved for external disclosure, such as a reviewed, de-identified control-flow constraint.
Do not copy private source bodies, secrets, or real names from ignored boundaries into a note.

Non-ignored Python files are analyzed locally. Only selected and approved function or class
excerpts can be exported verbatim; the source default is no. Verbatim source may contain
comments, docstrings, strings, and internal identifiers. A boundary reference additionally needs
exact `EXPOSE`, but siloBrief does not detect secrets or certify the result as safe. Review both
the main file and any `.sources.md` companion before sharing them.

## Commands

| Command | Behavior |
|---|---|
| `sb setup [PATH]` | Creates or validates `.silobrief/` state in an existing project. |
| `sb ignore PATH --as TEXT [--alias NAME]` | Excludes an existing path and registers its public boundary description. |
| `sb init` | Builds a deterministic structure index from allowed Python files. |
| `sb log PATH --comment TEXT` | Stores a user-authored note that may appear in a brief. |
| `sb chat "PROMPT" --out FILE` | Writes a reviewed main brief and optional approved `.sources.md` companion. |
| `sb --version` | Prints the installed siloBrief version. |

Commands other than `setup` discover the project root from the current directory. `chat`
requires an interactive terminal, a current index, and a new `.md` output path. Output inside
the project must be below `.silobrief/exports/`; existing files are never overwritten.

## Local state

```text
.silobrief/
├─ config.json
├─ index.json
├─ notes.json
└─ exports/
```

State files are local implementation data, not transfer-ready output. Only the generated main
brief and optional source companion are intended artifacts, and both still require a complete
human review before moving them.

## Exit codes

| Code | Meaning |
|---:|---|
| `0` | Success |
| `1` | Unexpected internal error |
| `2` | Input, path, or configuration error |
| `3` | Indexing or Python parsing error |
| `4` | Boundary validation, approval, or output was blocked |

## Boundaries

- Indexing does not follow symbolic links or open registered excluded subtrees.
- Boundary references are stored with an approved alias and description instead of their real
  excluded names.
- The tool does not use a network connection, language model, or automatic transfer.
- Path-based exclusions do not identify sensitive names inside otherwise allowed files.

siloBrief is not a security scanner, export-approval system, or guarantee against data
disclosure. Its effect on research speed and user demand has not been validated.

## Contributing

The project accepts changes through an Issue and a pull request to `develop`. Read
[`CONTRIBUTING.md`](CONTRIBUTING.md) before starting work.

## License

Apache License 2.0. See [`LICENSE`](LICENSE).
