# Contributing to siloBrief

Thank you for taking the time to improve siloBrief. Keep each change narrow enough to review
and reverse independently.

## Before you start

1. Search existing Issues.
2. Open an Issue that describes the problem, expected behavior, acceptance criteria, and what
   is out of scope.
3. Wait until the scope is clear before writing code.

Do not include real private repositories, organization details, credentials, or restricted
material in an Issue, test, fixture, or pull request.

## Branches

- `main` contains released code.
- `develop` is the integration branch.
- Start work from an up-to-date `develop` branch.

Use one of these branch formats:

```text
feat/<issue>-<slug>
fix/<issue>-<slug>
docs/<issue>-<slug>
chore/<issue>-<slug>
```

One branch should address one Issue.

## Commits

Commit subjects follow Conventional Commits:

```text
<type>(<scope>): <imperative description>
```

Allowed types are `feat`, `fix`, `docs`, `test`, `refactor`, `build`, `ci`, `chore`, and
`revert`. Write the subject in English, use the imperative mood, keep it within 72 characters,
and omit the final period.

Use a body when the reason is not obvious. Reference the Issue in the footer when useful:

```text
Refs #12
```

## Pull requests

- Target `develop` unless the change is an approved release or hotfix.
- Write the PR title as the Conventional Commit subject that should become the squash commit.
- Put `Refs #<issue>` in the body. Closing keywords only operate on the default branch, so the
  Issue is closed manually after a PR reaches `develop`.
- Explain why the change is needed, what changed, how it was checked, and what remains out of
  scope.
- Aim for about 200 changed production lines. Split the Issue before a PR exceeds 400 changed
  production lines.
- Resolve review conversations and delete the working branch after merge.

Feature, fix, documentation, and maintenance PRs are squash merged. Release PRs from `develop`
to `main` use a merge commit so the branch ancestry remains intact.

## Code and tests

- Support Python 3.10 and newer.
- Add complete parameter and return types to every function and method.
- Keep `mypy --strict` passing without per-module relaxations.
- Use the standard library at runtime.
- Write a failing acceptance or regression test before the smallest implementation.
- Avoid speculative abstractions, unused extension points, and comments that repeat the code.

Once the project tooling is present, run the checks documented in the PR template before
requesting review.

## Conduct and security

Participation is governed by [`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md). Report security
concerns using [`SECURITY.md`](SECURITY.md), not a public Issue.
