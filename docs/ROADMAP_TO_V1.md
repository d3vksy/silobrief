# Roadmap to siloBrief 1.0

Status: active implementation plan

This roadmap keeps siloBrief focused on one user and one job: a Python developer in a separated
environment must prepare a small, reviewable context packet for an external AI without treating
the whole repository as shareable.

The riskiest product assumption is not that this problem exists. It is that using siloBrief is
faster or produces better external-AI results than selecting and copying context manually.

## Scope through 1.0

The 1.0 product remains a local, dependency-free Python CLI. It indexes allowed Python source,
suggests relevant symbols, lets the user explicitly approve context and source excerpts, previews
one deterministic Markdown brief, and never connects to a model or network service.

The following are intentionally out of scope through 1.0:

- languages other than Python;
- direct LLM or network integration;
- GUI, IDE, team, account, or cloud features;
- a plugin or generalized extension system;
- a built-in secret scanner or export-approval claim.

## v0.7.0 — measurable retrieval

Question: can a user find the intended Python symbol without already knowing its exact path?

Deliverables:

- a versioned, deterministic retrieval benchmark with task text and expected symbols;
- Recall@10 and mean reciprocal rank reporting;
- an explainable ranking improvement that can use indexed call, reference, and import relations;
- regression tests proving deterministic results and boundary isolation.

Release gate:

- Recall@10 is at least 80% on the frozen benchmark;
- mean reciprocal rank is at least 0.50;
- no registered boundary content is read or emitted;
- Windows and Ubuntu produce the same ordered candidates for the same index.

## v0.8.0 — reviewable related context

Question: after finding the primary symbol, can the user add required cross-file context without
blindly including every adjacent symbol?

Deliverables:

- group related candidates by call, called-by, import, reference, and containment relation;
- show why every related candidate was proposed;
- ask for explicit per-item approval with a default of no;
- allow approved related functions and classes to enter the existing source-excerpt review;
- show the proposed disclosure size before the final write approval.

Release gate:

- no related item is included without an explicit approval;
- an excluded item cannot re-enter through graph expansion;
- source excerpts retain the existing preview, `EXPOSE`, digest, and `WRITE` safeguards;
- frozen comparison tasks record whether related context improves the resulting answer.

## v0.9.0 — public contract and distribution candidate

Question: can an unfamiliar user install, understand, upgrade, and operate the narrow workflow?

Deliverables:

- introduce `sb brief` as the accurate name for brief creation;
- retain `sb chat` as a documented deprecated alias and remove it only in a future major release;
- document the supported CLI, exit codes, local-state schemas, output schema, and compatibility
  policy;
- test upgrades from v0.6 state and clean wheel installation;
- prepare PyPI metadata, an installation guide, and a manual version-checked Trusted Publishing
  workflow without publishing before owner approval;
- provide a small public field-trial procedure.

Release gate:

- a clean environment can install the wheel and complete the guided example;
- v0.6 project state either loads successfully or fails with an actionable migration message;
- the supported contract is precise enough to apply Semantic Versioning after 1.0;
- all limitations continue to state that siloBrief is not a secret scanner or export approval.

## v1.0.0 — stable narrow contract

Version 1.0 adds no new product subsystem. It freezes the validated command and file contracts,
removes any pre-1.0 deprecated surface selected for removal, updates release metadata, and records
the final verification evidence.

GitHub issue #42 is included as a bounded release-candidate usability fix: `sb init` reports its
five existing phases only on an interactive terminal, using standard-library output and without
changing indexing, parallelizing work, or adding a package dependency.

Release gate:

- all v0.7, v0.8, and v0.9 gates pass from a clean checkout;
- lint, formatting, strict typing, unit tests, build, and installed-wheel tests pass;
- documentation and package metadata agree on version and supported behavior;
- `sb init` progress is visible on a TTY, absent from redirected output, and leaves index bytes
  unchanged;
- a release checklist records known limitations and any unvalidated demand claims;
- the owner explicitly approves the final tag, GitHub release, and any package publication.

## Stop or pivot criteria

Do not expand the product if retrieval remains below 70% Recall@10 after the planned explainable
ranking work, if related context does not improve frozen answer trials, or if completing a brief is
consistently slower than a manual packet. In those cases, keep the proven boundary-review utility,
reduce the product claim, and document the negative result rather than adding more subsystems.
