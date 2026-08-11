# siloBrief 1.0 public contract

Status: stable contract as of siloBrief 1.0.0

This document defines the surface that siloBrief 1.x intends to keep compatible. Anything not
listed here is an implementation detail.

## Product boundary

siloBrief is a local, dependency-free Python CLI. It reads allowed Python source below a configured
project root, builds a local index, proposes task-relevant symbols, and writes one reviewed Markdown
brief. It does not call an AI service, use the network, scan secrets, or certify an export as safe.

Supported runtime: CPython 3.10 or newer. CI verifies the lower and current upper tested versions on
Ubuntu and Windows. Python source is the only indexed language in 1.x.

## Stable commands

```text
sb setup [PATH]
sb example PATH
sb ignore PATH --as TEXT [--alias NAME]
sb unignore SELECTOR
sb init
sb log PATH --comment TEXT
sb search PROMPT
sb language [--cli en|ko] [--brief en|ko]
sb brief PROMPT --out FILE
sb --version
```

When standard error is a TTY, `sb init` renders one phase-based progress line there. It emits no
progress display when standard error is redirected or non-interactive, and progress reporting does
not affect index content, digests, normal standard output, or exit codes. Progress wording, bar
width, and internal phase boundaries are not stable APIs.

`sb brief` requires an interactive terminal. It confirms the request, presents ranked candidates,
shows up to ten one-hop related candidates with relation labels, accepts explicit `rN` approvals,
reviews every disclosure field and source excerpt, previews the full output, and requires exact
`WRITE` approval before creating a file.

`sb chat` is a deprecated compatibility alias for `sb brief`. It emits a warning to standard error.
It is not the documented primary command and will not be removed before a future 2.0 release.

Candidate scores, tie-break weights, the number of ordinary candidates below the documented upper
bound, explanatory wording, and internal Python modules are not stable APIs.

## Exit codes

| Code | Contract |
|---:|---|
| 0 | The command completed successfully. |
| 1 | The process stopped on an unexpected internal error. |
| 2 | Command syntax, setup state, configuration, or a user-supplied value is invalid. |
| 3 | A local index could not be built or loaded as valid state. |
| 4 | Source changed during processing, interactive review was rejected, or output was blocked. |

No nonzero result means that an export was approved. Callers must inspect standard error for the
specific failure and must not assume that a requested output file exists.

## Local state schemas

All state lives below `.silobrief/`. JSON files are UTF-8 objects. Canonical files written by
siloBrief use LF, sorted keys, two-space indentation, and a final newline.

### `config.json` schema 1

- `schema_version`: integer `1`;
- `default_excludes`: the exact version-1 default list;
- `boundaries`: objects with `path`, `alias`, and nonblank `description` strings.

### `notes.json` version 1

- `notes_version`: integer `1`;
- `notes`: objects with relative `path`, nonblank `comment`, and deterministic `note-<sha256>` ID.

### `language.json` version 1

- `settings_version`: integer `1`;
- `cli_language` and `brief_language`: `en` or `ko`.

The file may be absent in state created before language settings existed; readers then use English
defaults. A later save creates the current file.

### `index.json` version 1

The regenerable index stores `index_version`, `config_digest`, `source_digest`, `stale`, `nodes`, and
`edges`. Nodes contain only indexed structural/search data. Edges are `contains`, `import`, `call`,
or `reference`. Boundary targets use an approved alias and description instead of the excluded
target's real path or symbol. Run `sb init` to replace a stale or incompatible index.

Version 1.0 reads valid v0.6 schema-1 project state without rewriting configuration, notes, or
language settings. Unknown or incompatible config/notes/language schemas fail closed; siloBrief does
not guess a destructive migration.

## Generated Markdown contract

`sb brief` creates one new `.md` file and never overwrites an existing file. A relative path inside
the project must be below `.silobrief/exports/`. The document includes:

1. an execution instruction and disclosure warning;
2. the exact task text;
3. only explicitly approved paths, symbols, public imports, notes, and boundary placeholders;
4. only source excerpts separately approved after verbatim preview;
5. an external-response format contract; and
6. a YAML disclosure manifest with `schema_version: 3`.

Manifest schema 3 reports counts and source-delivery metadata, including `source_excerpts`,
`source_lines`, `source_utf8_bytes`, `source_content_mode`, and
`boundary_aliases_exposed_in_source`. It also records that the renderer added zero absolute paths and
zero Git remotes.

Markdown wording and section prose may improve in a 1.x release. The disclosure manifest version is
the machine-readable compatibility boundary; consumers must reject an unsupported schema rather
than infer fields from prose.

## Compatibility policy

siloBrief follows Semantic Versioning for the contract above after 1.0. Patch releases fix behavior
without intentionally changing the contract. Minor releases may add commands, optional fields under
a new documented schema, or new opt-in behavior while retaining existing 1.x workflows. Removing or
changing a stable command, exit-code meaning, accepted state schema, or manifest field requires a
major release.

Security fixes may narrow unsafe behavior immediately. Such a change will be called out explicitly
even when it requires rejecting an input accepted by an earlier version.

## Known limitations

- Ranking is advisory and the frozen benchmark is small.
- Related-context tests prove approval isolation, not better external-model answers.
- Source inside allowed paths may contain secrets or identifiers that siloBrief does not classify.
- Human notes are unclassified user input.
- There is no automatic transfer, policy engine, team approval, or security guarantee.
