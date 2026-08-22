# Contributing to siloBrief

Thank you for taking the time to improve siloBrief. Keep each change narrow enough to review
and reverse independently.

## Before you start

1. Search existing Issues.
2. Open an Issue that describes the problem, expected behavior, and acceptance criteria.
3. Wait until the scope is clear before writing code.

Do not include real private repositories, organization details, credentials, or restricted
material in an Issue, test, fixture, or pull request.

## Issues

Issue titles use the same shape as Conventional Commit subjects:

```text
<type>(<scope>): <imperative description>
```

Use the types listed under [Commits](#commits). In particular, use `feat` for new behavior, `fix`
for incorrect behavior, `docs` for documentation, `test` for validation work, and `chore` for
releases or repository maintenance. Use a short lowercase scope such as `example`, `index`, or
`release`. Write the description in English, use the imperative mood, keep the whole title within
72 characters, and omit the final period.

```text
feat(example): add a guided practice project
fix(index): preserve top-level package names
docs(readme): clarify the quick start
```

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
- Explain why the change is needed, what changed, and how it was checked.
- Aim for about 200 changed production lines. Split the Issue before a PR exceeds 400 changed
  production lines.
- Resolve review conversations and delete the working branch after merge.

Feature, fix, documentation, and maintenance PRs are squash merged. Release PRs from `develop`
to `main` use a merge commit so the branch ancestry remains intact.

## Publishing to PyPI

PyPI publication uses `.github/workflows/publish-pypi.yml` and Trusted Publishing. Before the first
publication, complete these one-time settings:

1. Create a GitHub environment named `pypi` and require manual approval for deployments.
2. On PyPI, register a pending Trusted Publisher with project `silobrief`, owner `d3vksy`,
   repository `silobrief`, workflow `publish-pypi.yml`, and environment `pypi`.
3. Protect tags matching `v*` so only the maintainer can create or change release tags.

No PyPI API token or GitHub secret is used. To publish, first make sure `pyproject.toml` contains the
approved version and the matching `vVERSION` tag points to a commit reachable from `main`. In
GitHub, open **Actions → Publish to PyPI → Run workflow**, leave the workflow branch on `main`, and
enter `VERSION` without the `v` prefix, such as `1.0.0`. Approve the `pypi` environment deployment
after reviewing the build job.

The workflow fails closed when the input, tag, source metadata, or built artifact versions differ.
PyPI does not permit replacing an already published version, so choose a new version for every
retry after a successful upload.

## Code and tests

- Support Python 3.10 and newer.
- Add complete parameter and return types to every function and method.
- Keep `mypy --strict` passing without per-module relaxations.
- Use the standard library at runtime.
- Increase `INDEX_VERSION` whenever a change alters stored nodes, edges, search tokens, or their
  meaning. siloBrief will then reject older indexes until the user runs `sb init`.
- Write a failing acceptance or regression test before the smallest implementation.
- Avoid speculative abstractions, unused extension points, and comments that repeat the code.

Once the project tooling is present, run the checks documented in the PR template before
requesting review.

## Conduct and security

Participation is governed by [`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md). Report security
concerns using [`SECURITY.md`](SECURITY.md), not a public Issue.
