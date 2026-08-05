# siloBrief

[한국어](README.ko.md)

siloBrief helps Python developers choose what project information and source code to share with
an external AI assistant. It works locally, shows everything before writing, and creates Markdown
files that you transfer yourself.

Use it when an AI assistant cannot access your repository and some project paths must stay out of
the material you share.

siloBrief does not connect to an AI service or send files over the network.

## What it produces

You give siloBrief a development task and review the project items it finds. The result can
contain two files:

```text
retry-brief.md          task and approved project context
retry-brief.sources.md  source code you selected and approved
```

Send both files to the AI assistant when the `.sources.md` file exists. If you decline every
source selection, siloBrief creates only the main brief.

See a generated [main brief](validation/v0.2/packets/T01-MODIFY/t01-modify.md) and its
[code attachment](validation/v0.2/packets/T01-MODIFY/t01-modify.sources.md).

## How it works

1. `setup` creates local siloBrief state in an existing project.
2. `ignore` registers paths that siloBrief must not read.
3. `init` scans the remaining Python files and builds a local search list.
4. `log` optionally records a project fact that the code structure cannot show.
5. `chat` finds relevant functions and classes, then asks you what may be included.
6. After a complete preview and exact `WRITE` approval, siloBrief creates the Markdown files.

The generated files are inputs for another AI assistant. siloBrief does not generate the code
change itself.

## Install

Requirements:

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

## Try the complete workflow

Copy the synthetic [`parcel-sync-fixture`](examples/parcel-sync-fixture/README.md) to a disposable
directory. Run the following commands from the copied project root:

```console
sb setup .
sb ignore private_adapter --as "External delivery adapter" --alias delivery-boundary
sb init
sb log src/parcel_sync/service.py --comment "HTTP 503 responses may be retried."
sb chat "Update retry_request to retry HTTP 503 but not 500. Return a unified diff and tests." --out .silobrief/exports/retry-brief.md
```

During `chat`:

1. Confirm the task and choose the relevant function or class.
2. Review each proposed project field.
3. Choose whether to include the displayed source code. The default answer is no.
4. If the source reveals an excluded boundary identifier, type `EXPOSE` only after reviewing it.
5. Review the complete main brief and code attachment.
6. Type `WRITE` to create the files.

Open both generated files before moving them to a different environment.

## Write a useful task

Write `PROMPT` as a concrete task instead of a few keywords. State the required deliverables and
acceptance criteria so the AI assistant can tell what a complete answer must contain.

Enter only information approved for external disclosure with `sb log`.
Do not put private source code, secrets, or real names from excluded areas in a project note. Only
source code you select and approve can be included verbatim in the code attachment; the default
answer is no.

## Terms used in this project

| Term | Plain meaning |
|---|---|
| Main brief | The main `.md` file containing the task and approved project context. It does not contain source code bodies. |
| Code attachment | The optional `.sources.md` file containing source code selected and approved by the user. The technical contract calls this the source companion. |
| Excluded path | A file or directory registered with `sb ignore`. siloBrief does not scan files below an excluded directory. |
| Public name for an excluded area | An alias and description used in place of the excluded path's real name. The technical contract calls this a boundary alias. |
| Local search list | `.silobrief/index.json`, which records allowed Python files, functions, and classes. The technical contract calls this the index. |
| Project note | A user-written fact saved with `sb log` that may be offered during review. |

## Commands

| Command | What it does |
|---|---|
| `sb setup [PATH]` | Adds or checks local siloBrief state in an existing project. |
| `sb ignore PATH --as TEXT [--alias NAME]` | Excludes a path and records a public label for that boundary. |
| `sb init` | Builds the local search list from allowed Python files. |
| `sb log PATH --comment TEXT` | Saves an approved project note. |
| `sb chat "PROMPT" --out FILE` | Reviews context and writes the main brief and optional code attachment. |
| `sb --version` | Prints the installed siloBrief version. |

Commands other than `setup` find the project root from the current directory. `chat` requires an
interactive terminal, a current index, and a new `.md` output path. Output inside the project must
be below `.silobrief/exports/`. Existing files are never overwritten.

## What siloBrief does and does not protect

siloBrief:

- does not follow symbolic links while indexing;
- does not open registered excluded subtrees;
- replaces references to excluded code with an approved public label in the main brief;
- requires a preview before writing output; and
- uses no network connection, language model, or automatic transfer.

siloBrief does not detect secrets inside allowed files or clean text entered with `sb log`.
Approved source code can contain comments, docstrings, strings, and internal identifiers. It is
not a security scanner, an organizational export-approval system, or a guarantee against
disclosure. Review every generated file before sharing it.

## Current evidence

The current release is v0.2.0. The same package produced identical Markdown files on Windows and
Ubuntu. Claude completed three example code-maintenance tasks using those files.
GPT validation remains follow-up work. These results do not establish effectiveness across
models, real private projects, or independent users.

- [Installed wheel verification](validation/v0.2/INSTALLED_WHEEL_VERIFICATION.md)
- [Manual model gate](validation/v0.2/MANUAL_MODEL_GATE.md)
- [Claude gate result](validation/v0.2/results/CLAUDE_GATE_RESULT.md)

## Technical reference

- [v0.2 behavior contract](docs/V0_2_CONTRACT.md)
- [Contributing guide](CONTRIBUTING.md)
- [Security policy](SECURITY.md)

## Exit codes

| Code | Meaning |
|---:|---|
| `0` | Success |
| `1` | Unexpected internal error |
| `2` | Input, path, or configuration error |
| `3` | Indexing or Python parsing error |
| `4` | Boundary validation, approval, or output was blocked |

## License

Apache License 2.0. See [`LICENSE`](LICENSE).
