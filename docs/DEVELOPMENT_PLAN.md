# Development plan

This file records the maintainer's v0.1 implementation sequence. It does not impose a timed
commit schedule on external contributors.

## Working rhythm

- Keep one active implementation Issue at a time.
- Divide work into roughly one-hour units that can be reviewed and tested independently.
- Commit only when a unit has a coherent result; do not commit incomplete code to meet a clock.
- Small typo, CI, and immediate regression fixes may follow within the same PR without waiting.
- Report the diff and test result after each meaningful commit before starting another feature.
- Use actual commit times. Do not backdate or alter history to create an artificial timeline.
- Keep production changes near 200 lines per PR and split the Issue before 400 lines.

## Repository flow

```text
Issue
→ branch from develop
→ acceptance or regression test
→ minimum implementation
→ draft PR to develop with Refs #N
→ checks and review
→ squash merge
→ manual Issue close
```

`main` contains releases and `develop` contains integrated work. The `develop → main` release
PR is the only normal merge-commit exception. A release hotfix starts from `main` and is then
backported to `develop` through a second PR.

## v0.1 Issues

1. Contribution workflow
2. Package and version
3. Project setup
4. Boundary registration
5. Safe traversal and source digest
6. Python structure extraction
7. Deterministic index
8. Boundary placeholders
9. Human notes
10. Lexical ranking
11. Interactive review
12. Brief renderer
13. Approval and output guards
14. Public fixture and end-to-end demo
15. v0.1.0 release

Each Issue must state the user or maintainer problem, acceptance criteria, and excluded work.
Features not required by `docs/V0_1_CONTRACT.md` are not added to v0.1.

## Release checkpoints

- Keep the GitHub repository private during v0.1 development.
- Reproduce the acceptance demo on Windows and Ubuntu before release.
- Build and install the wheel and source distribution before tagging.
- Merge `develop` into `main` with `release: v0.1.0`.
- Make the repository public with the v0.1.0 GitHub Release.
- Do not publish v0.1.0 to PyPI.
