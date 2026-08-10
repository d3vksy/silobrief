# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this
project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Create a deterministic synthetic Python practice project with `sb example PATH`, including
  guided modification, addition, and removal tasks.
- Configure terminal guidance and generated Markdown independently in English or Korean with
  `sb language`; both settings default to English.

## [0.5.0] - 2026-08-09

### Added

- Inspect up to ten deterministic code candidates with `sb search`, including the exact request
  terms matched by each indexed field.

### Changed

- Show concrete matching terms instead of only match counts during `sb chat` candidate review.
- Write the task, approved context, and approved source excerpts into one self-contained Markdown
  file instead of a main brief plus `.sources.md` companion.
- Record embedded source with disclosure manifest schema 3 and `source_delivery`.

### Known limitations

- Candidate search remains lexical and advisory. It does not automatically identify or approve
  every source excerpt required for a change.
- The intended symbol appeared in the Top 10 for three of six prompts in the existing lexical
  regression set. Guided exact-path selection remains necessary when search misses.
- This release does not validate automatic context closure, secret detection, export approval,
  market demand, or answer quality across external AI models.

## [0.4.0] - 2026-08-09

### Added

- Remove one registered boundary by its exact stored path or alias with `sb unignore`, leaving the
  current index stale until the user runs `sb init` again.

### Fixed

- Keep exact-path symbol selection focused on the chosen symbols instead of expanding the whole
  module.
- Replace excluded src-layout module and symbol names with their registered boundary placeholder
  in the index and generated brief.

### Known limitations

- Exact-path recovery remains guided selection: the user must know an indexed relative Python
  file path.
- The installed-wheel workflow passed on six frozen open-source repositories, but independent
  lexical retrieval reached the intended symbol in the Top 10 for only one of six tasks.
- This release does not establish secret detection, export approval, market demand, or general
  answer quality across external AI models.

## [0.3.0] - 2026-08-06

### Added

- Continue an interactive review with an exact indexed Python file path and select its classes or
  functions, including when lexical search finds no candidates.

### Changed

- Search comments and docstrings only within their owning module, class, or function instead of
  copying module-wide text into every index node.
- Run `sb init` once after upgrading to rebuild an existing index with scoped text tokens.
- Explain the Python-only scope when indexing finds no supported source files or a review has no
  indexed symbols.

### Known limitations

- Source indexing supports Python only. A project with no indexed Python symbols is rejected before
  review instead of producing an empty brief.
- Exact-path recovery is guided selection, not semantic retrieval; the user must know an indexed
  relative Python file path.
- GPT and independent real-project validation remain follow-up work. This release does not
  establish cross-model effectiveness, security, or demand.

## [0.2.0] - 2026-08-05

### Added

- Explicit review of selected function and class source excerpts with optional paired
  `.sources.md` output.
- Additional `EXPOSE` approval for boundary identifiers visible in approved source.

### Changed

- `sb setup` and the public guides now warn that approved source is copied verbatim and that
  siloBrief does not detect secrets or provide security approval.
- Generated briefs now start with one execution instruction, omit empty context sections, and no
  longer repeat the task in a copy prompt or include a user-only checklist.
- External model responses are now required to use readable diff-style blocks with explicit
  removed and added lines, without requiring machine-applicable hunk metadata.

### Known limitations

- Claude passed all three synthetic maintenance tasks, but GPT and real-project validation remain
  follow-up work; this release does not establish cross-model effectiveness, security, or demand.

## [0.1.0] - 2026-08-04

### Added

- Initial project contract and contribution workflow.
- Installable `silobrief` package and `sb --version` command.
- Deterministic and idempotent project initialization with `sb setup`.
- Guarded project boundary registration with `sb ignore`.
- Safe source traversal, parsing, and deterministic indexing with `sb init`.
- Boundary placeholders that omit registered subtree names from stored indexes and briefs.
- User-authored public project notes with `sb log`.
- Explainable lexical ranking and interactive one-step context review.
- Whitelist-based Markdown rendering through `sb chat`.
- Full preview and exact `WRITE` approval before creating a new output file.
- Synthetic `parcel-sync-fixture` and installed-wheel end-to-end acceptance coverage.
- English and Korean guidance for writing useful prompts and approved public notes.

### Fixed

- Included public documentation and the synthetic fixture in source distributions.
- Excluded unresolved relative imports from public dependency disclosure.
- Reported whether `sb setup` created new state or validated existing state.
- Rejected an empty `sb` invocation with usage and exit code `2`.

### Known limitations

- Generated briefs do not automatically contain source bodies or implementation excerpts.
- Exclusions are path-based and cannot identify sensitive names inside otherwise allowed files.
- siloBrief is not a security scanner, export-approval system, or disclosure guarantee.
- The tool uses lexical ranking and requires a complete human review before a brief is shared.
- Research-speed effects and user demand remain unvalidated.
