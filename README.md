<p align="center">
  <img src=".github/assets/silobrief-wordmark.svg" alt="siloBrief" width="840">
</p>

---

<p align="center">
  <a href="https://github.com/d3vksy/silobrief/actions/workflows/ci.yml"><img src="https://github.com/d3vksy/silobrief/actions/workflows/ci.yml/badge.svg?branch=main" alt="CI status"></a>
  <a href="https://github.com/d3vksy/silobrief/releases/tag/v1.0.1"><img src="https://img.shields.io/badge/release-v1.0.1-4f46e5" alt="Release v1.0.1"></a>
  <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/python-3.10%2B-3776ab" alt="Python 3.10 or newer"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-Apache--2.0-0f766e" alt="Apache 2.0 license"></a>
</p>

<p align="center">
  <a href="#quick-start">Quick start</a> •
  <a href="#how-it-works">How it works</a> •
  <a href="#commands">Commands</a> •
  <a href="#safety-and-limitations">Safety</a> •
  <a href="#validation-status">Validation</a> •
  <a href="#security">Security</a> •
  <a href="README.ko.md">한국어</a>
</p>

In a closed network or internal development environment, an external AI assistant cannot access the
repository directly. Developers must prepare the relevant code and project context separately.

siloBrief is a local CLI that turns approved Python project context into a Markdown brief. You choose
the information and source excerpts before writing the file. The result is input for another tool,
not a generated code change.

- License: Apache License 2.0
- Platforms: Windows and Ubuntu
- Python: 3.10 and newer
- Runtime dependencies: none
- Network access: none

## Quick start

### Install

Install the stable package from PyPI and verify the command:

```console
python -m pip install silobrief
sb --version
```

Expected output:

```text
siloBrief 1.0.1
```

### Practice project

Create a practice project:

```console
sb example ./silobrief-practice
cd silobrief-practice
```

The generated `README.md` guides you through one modification, one addition, and one removal task.

Start the first task from the same directory:

```console
sb setup .
sb init
sb log parcel_practice/labels.py --comment "Callers pass uppercase positionally."
sb search "Append an optional separator to format_label. Preserve positional callers and apply uppercase last."
sb brief "Append an optional separator to format_label. Preserve positional callers and apply uppercase last. Return a readable diff and focused unittests." --out .silobrief/exports/task-01-modify.md
```

`setup` prepares local state, and `init` indexes the Python files. `log` records approved project
context. `search` shows ranked candidates, and `brief` starts the review that produces the Markdown
file.

## How it works

### Set project boundaries

Register paths that siloBrief must skip before building the index:

```console
sb ignore private_adapter --as "External delivery adapter" --alias delivery-boundary
sb init
```

If a boundary is no longer needed, remove it by its stored path or alias and rebuild the index:

```console
sb unignore delivery-boundary
sb init
```

`unignore` changes the local configuration without opening the target. It marks the current index as
stale, so `sb brief` remains blocked until `sb init` finishes. Files under the removed boundary may
then appear as review candidates.

### Add project context

Use `sb log` for a project fact that the code alone does not explain:

```console
sb log src/parcel_sync/service.py --comment "HTTP 503 responses may be retried."
```

Enter only information approved for external disclosure. Do not put private source code, secrets,
or real names from excluded areas in a project note.

### Review and write

Start a review with a concrete task:

```console
sb brief "Update retry_request to retry HTTP 503 but not 500. Return a unified diff and tests." --out .silobrief/exports/retry-with-note.md
```

During `brief`:

1. Confirm the task and choose the relevant function or class. If the suggested candidates miss the
   target, enter an exact indexed Python file path and select its functions or classes.
2. Review one-hop related context and type an `rN` value only for an item you want to add. Blank input
   approves none.
3. Review each proposed project field.
4. Choose whether to include the displayed source code. The default answer is no.
5. If the source reveals an excluded boundary identifier, type `EXPOSE` after reviewing it.
6. Review the complete brief.
7. Type `WRITE` to create the file.

The result is one Markdown brief containing the task, approved project context, and any source code
you select and approve. Selected source is included verbatim. If you decline every source selection,
the file contains only the task and approved project context. Open the file before moving it to a
different environment.

### Choose interface and brief languages

The terminal interface and generated brief default to English. Settings are stored per project and
can be changed together or separately:

```console
sb language --cli ko
sb language --brief en
sb language
```

The CLI setting changes fixed terminal guidance. The brief setting changes generated headings and
instructions. Task text, project notes, source code, paths, symbols, and identifiers remain as
entered or selected. Language settings do not affect indexing, candidate ranking, IDs, ordering, or
source digests.

### Write a useful task

Write `PROMPT` as a concrete task, not a list of keywords. Include the required deliverables and
acceptance criteria so the receiving assistant can tell when the work is complete.

## Commands

| Command | What it does |
|---|---|
| `sb setup [PATH]` | Adds or checks local siloBrief state in an existing project. |
| `sb example PATH` | Creates a synthetic project with three guided maintenance tasks. |
| `sb ignore PATH --as TEXT [--alias NAME]` | Excludes a path and records a public label for that boundary. |
| `sb unignore SELECTOR` | Removes one registered boundary by its exact stored path or alias. |
| `sb init` | Builds the local search list from allowed Python files. |
| `sb log PATH --comment TEXT` | Saves an approved project note. |
| `sb search "PROMPT"` | Lists a bounded set of code candidates and the request terms that matched each one. |
| `sb language [--cli {en,ko}] [--brief {en,ko}]` | Sets terminal and generated-brief languages independently. |
| `sb brief "PROMPT" --out FILE` | Reviews context and writes one Markdown brief. |
| `sb chat "PROMPT" --out FILE` | Previous name for `sb brief`, kept for existing users. |
| `sb --version` | Prints the installed siloBrief version. |

Commands other than `setup` and `example` find the project root from the current directory. `brief`
requires an interactive terminal, a current index, and a new `.md` output path. Output inside the
project must be below `.silobrief/exports/`. Existing files are never overwritten.

When standard error is an interactive terminal, `sb init` shows one progress line for source
collection, analysis, index construction, source-change verification, and writing. Redirected output
and CI runs omit the progress display. The success message remains on standard output.

## Safety and limitations

siloBrief does not read registered excluded paths or follow symbolic links while indexing.
References to excluded code use the public label you approved. Before it writes a brief, you review
the complete output and choose which source excerpts to include.

It does not detect secrets in allowed files or text entered with `sb log`. Approved source code may
contain comments, docstrings, strings, and internal identifiers. siloBrief is not a security scanner
or an export-approval system for a closed environment. Review every generated file under your
organization's disclosure rules before sharing it.

## Validation status

The latest public release is v1.0.1 and follows the supported 1.x compatibility contract. In the
frozen retrieval benchmark, `sb search` reaches an expected symbol for 11 of 12 tasks, with a mean
reciprocal rank of 72.2%. Candidate search is lexical and advisory. When it misses, use the exact
indexed Python file path during review.

The deterministic end-to-end flow was verified on Django Ninja, pytest, and Jinja checkouts without
changing their Python source files. The benchmark is small and does not establish effectiveness
across other AI models or private projects.

- [Installed wheel verification](validation/v0.2/INSTALLED_WHEEL_VERIFICATION.md)
- [Manual model gate](validation/v0.2/MANUAL_MODEL_GATE.md)
- [Claude gate result](validation/v0.2/results/CLAUDE_GATE_RESULT.md)
- [v0.7 retrieval result](validation/v0.7/RETRIEVAL_RESULT.md)
- [v0.8 related-context result](validation/v0.8/RELATED_CONTEXT_RESULT.md)
- [Solo field-trial procedure](validation/v0.9/FIELD_TRIAL.md)
- [v1.0.1 release verification](validation/v1.0.1/RELEASE_VERIFICATION.md)

## Exit codes

| Code | Meaning |
|---:|---|
| `0` | Success |
| `1` | Unexpected internal error |
| `2` | Input, path, or configuration error |
| `3` | Indexing or Python parsing error |
| `4` | Boundary validation, approval, or output was blocked |

## Security

See the [security policy](SECURITY.md) for vulnerability reporting guidance.

## Contributing

Contributions are welcome. Read the [contributing guide](CONTRIBUTING.md) before opening an issue or
pull request. Everyone participating in the project must follow the
[code of conduct](CODE_OF_CONDUCT.md).

## License

siloBrief is distributed under the Apache License 2.0. See [`LICENSE`](LICENSE).
