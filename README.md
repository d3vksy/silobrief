<p align="center">
  <img src="docs/assets/silobrief-wordmark.svg" alt="siloBrief" width="840">
</p>

---

<p align="center">
  <a href="https://github.com/d3vksy/silobrief/actions/workflows/ci.yml"><img src="https://github.com/d3vksy/silobrief/actions/workflows/ci.yml/badge.svg?branch=main" alt="CI status"></a>
  <a href="https://github.com/d3vksy/silobrief/releases/tag/v0.4.0"><img src="https://img.shields.io/badge/release-v0.4.0-4f46e5" alt="Release v0.4.0"></a>
  <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/python-3.10%2B-3776ab" alt="Python 3.10 or newer"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-Apache--2.0-0f766e" alt="Apache 2.0 license"></a>
</p>

<p align="center">
  <a href="#mission">Mission</a> •
  <a href="#installation">Installation</a> •
  <a href="#commands">Commands</a> •
  <a href="#usage">Usage</a> •
  <a href="#safety-and-limitations">Safety</a> •
  <a href="#documentation">Documentation</a> •
  <a href="README.ko.md">한국어</a>
</p>

In a closed network or an internal development environment, an external AI assistant cannot access
the repository directly. Relevant code and project context must be prepared separately, but sending
the entire repository is often unacceptable.

siloBrief is a local command-line tool that turns a development task and user-approved context from
a closed Python project into reviewable Markdown. You choose which source code may be included,
preview the complete result, and transfer the files under your organization's disclosure process.
siloBrief does not connect to an AI service or send files over the network.

- Free software: Apache License 2.0
- Platforms: Windows and Ubuntu
- Python versions: 3.10 and newer
- Runtime dependencies: none

## Mission

Our mission is to make context from a project that external AI cannot access useful without treating
the whole repository as shareable. siloBrief provides:

- boundary registration before source indexing;
- local discovery of relevant Python functions and classes;
- explicit review of every context item and source-code selection;
- a complete preview before files are written; and
- deterministic Markdown that can be inspected and moved manually.

The generated files are inputs for another AI assistant. siloBrief does not generate the code
change itself.

## Installation

Install the current checkout and verify the command:

```console
python -m pip install .
sb --version
```

Expected output:

```text
siloBrief 0.4.0
```

## Commands

| Command | What it does |
|---|---|
| `sb setup [PATH]` | Adds or checks local siloBrief state in an existing project. |
| `sb ignore PATH --as TEXT [--alias NAME]` | Excludes a path and records a public label for that boundary. |
| `sb unignore SELECTOR` | Removes one registered boundary by its exact stored path or alias. |
| `sb init` | Builds the local search list from allowed Python files. |
| `sb log PATH --comment TEXT` | Saves an approved project note. |
| `sb search "PROMPT"` | Lists up to ten code candidates and the request terms that matched each one. |
| `sb chat "PROMPT" --out FILE` | Reviews context and writes the main brief and optional code attachment. |
| `sb --version` | Prints the installed siloBrief version. |

Commands other than `setup` find the project root from the current directory. `chat` requires an
interactive terminal, a current index, and a new `.md` output path. Output inside the project must
be below `.silobrief/exports/`. Existing files are never overwritten.

## Generated files

A review can produce two files:

```text
retry-brief.md          task and approved project context
retry-brief.sources.md  source code you selected and approved
```

Send both files to the AI assistant when the `.sources.md` file exists. If you decline every
source selection, siloBrief creates only the main brief.

See a generated [main brief](validation/v0.2/packets/T01-MODIFY/t01-modify.md) and its
[code attachment](validation/v0.2/packets/T01-MODIFY/t01-modify.sources.md).

## Usage

### Basic example

Copy the synthetic [`parcel-sync-fixture`](examples/parcel-sync-fixture/README.md) to a disposable
directory. Run these commands from the copied project root:

```console
sb setup .
sb ignore private_adapter --as "External delivery adapter" --alias delivery-boundary
sb init
sb search "Update retry_request to retry HTTP 503 but not 500."
sb chat "Update retry_request to retry HTTP 503 but not 500. Return a unified diff and tests." --out .silobrief/exports/retry-brief.md
```

`setup` prepares local state, `ignore` registers a path that must not be read, and `init` builds a
local search list from the remaining Python files. `search` lets you inspect ranked candidates
without starting disclosure review. `chat` uses the same candidates and then asks you to choose
what may be included.

### Remove a registered boundary

If an ignore entry is no longer correct, remove it by the exact stored path or alias, then rebuild
the index:

```console
sb unignore delivery-boundary
sb init
```

`unignore` changes only local configuration and does not open the removed path. It marks an existing
index as stale, so `sb chat` remains blocked until `sb init` finishes. After rebuilding, files below
that path may be offered for review and source disclosure.

### Complete review

Add an approved project fact when code structure alone does not explain the task:

```console
sb log src/parcel_sync/service.py --comment "HTTP 503 responses may be retried."
sb chat "Update retry_request to retry HTTP 503 but not 500. Return a unified diff and tests." --out .silobrief/exports/retry-with-note.md
```

During `chat`:

1. Confirm the task and choose the relevant function or class. If the suggested candidates miss
   the target, enter an exact indexed Python file path and select its functions or classes.
2. Review each proposed project field.
3. Choose whether to include the displayed source code. The default answer is no.
4. If the source reveals an excluded boundary identifier, type `EXPOSE` only after reviewing it.
5. Review the complete main brief and code attachment.
6. Type `WRITE` to create the files.

Open both generated files before moving them to a different environment.

### Write a useful task

Write `PROMPT` as a concrete task instead of a few keywords. State the required deliverables and
acceptance criteria so the AI assistant can tell what a complete answer must contain.

Enter only information approved for external disclosure with `sb log`. Do not put private source code,
secrets, or real names from excluded areas in a project note. Only source code you select and approve
can be included verbatim in the code attachment; the default answer is no.

## Terms

| Term | Plain meaning |
|---|---|
| Main brief | The main `.md` file containing the task and approved project context. It does not contain source code bodies. |
| Code attachment | The optional `.sources.md` file containing source code selected and approved by the user. The technical contract calls this the source companion. |
| Excluded path | A file or directory registered with `sb ignore`. siloBrief does not scan files below an excluded directory. |
| Public name for an excluded area | An alias and description used in place of the excluded path's real name. The technical contract calls this a boundary alias. |
| Local search list | `.silobrief/index.json`, which records allowed Python files, functions, and classes. The technical contract calls this the index. |
| Project note | A user-written fact saved with `sb log` that may be offered during review. |

## Safety and limitations

siloBrief:

- does not follow symbolic links while indexing;
- does not open registered excluded subtrees;
- does not open a boundary target while removing its registration;
- replaces references to excluded code with an approved public label in the main brief;
- requires a preview before writing output; and
- uses no network connection, language model, or automatic transfer.

siloBrief does not detect secrets inside allowed files or clean text entered with `sb log`.
Approved source code can contain comments, docstrings, strings, and internal identifiers. It is
not a security scanner, an export-approval system for a closed environment, or a guarantee against
disclosure. Review every generated file under your organization's disclosure rules before sharing it.

## Validation status

The current release is v0.4.0. It can remove one registered boundary by path or alias with
`sb unignore`, then requires `sb init` before review. Exact-path review now keeps source disclosure
focused on the symbols the user selected.

The installed-wheel workflow passed on six frozen open-source Python repositories, including
boundary removal, stale-index blocking, exact-path review, and paired Markdown output. Automatic
lexical retrieval found the intended symbol in the Top 10 for only one of six independent tasks, so
guided path selection remains important. These results do not establish secret detection, export
approval, market demand, or effectiveness across external AI models and private projects.

- [Installed wheel verification](validation/v0.2/INSTALLED_WHEEL_VERIFICATION.md)
- [Manual model gate](validation/v0.2/MANUAL_MODEL_GATE.md)
- [Claude gate result](validation/v0.2/results/CLAUDE_GATE_RESULT.md)

## Exit codes

| Code | Meaning |
|---:|---|
| `0` | Success |
| `1` | Unexpected internal error |
| `2` | Input, path, or configuration error |
| `3` | Indexing or Python parsing error |
| `4` | Boundary validation, approval, or output was blocked |

## Documentation

- [Output and safety contract](docs/V0_2_CONTRACT.md)
- [Security policy](SECURITY.md)

## Contributing

Contributions are welcome. Read the [contributing guide](CONTRIBUTING.md) before opening an issue
or pull request. Everyone participating in the project must follow the
[code of conduct](CODE_OF_CONDUCT.md).

## License

siloBrief is distributed under the Apache License 2.0. See [`LICENSE`](LICENSE).

## Disclaimer

siloBrief is provided as-is. It helps you review files for manual disclosure, but it does not
decide whether information is safe or authorized to share. Use it with your project's disclosure
rules and review every output yourself.
