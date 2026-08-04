# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this
project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Explicit review of selected function and class source excerpts with optional paired
  `.sources.md` output.
- Additional `EXPOSE` approval for boundary identifiers visible in approved source.

### Changed

- `sb setup` and the public guides now warn that approved source is copied verbatim and that
  siloBrief does not detect secrets or provide security approval.
- Generated briefs now start with one execution instruction, omit empty context sections, and no
  longer repeat the task in a copy prompt or include a user-only checklist.

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
