# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this
project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
