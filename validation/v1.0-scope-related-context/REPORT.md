# Scope-related one-hop context validation

## Decision

Proceed with the lexical-scope correction. The fixed-primary comparison affected three of the 12
holdout tasks, met every gate in Issue #185, and improved the required related context in two cases.
This result supports the scope fix only; it does not justify a graph database, multi-hop expansion,
or an LLM-based retrieval layer.

## Frozen protocol

- Baseline: `e5329b29d884d40dc7d3b14ca7fa26c83a14878b`
- Current: `ab98e39910d9dc70eacdad3fcb4df4d5e7b579de`
- Corpus: the six v0.4 ranking holdouts and six v0.4 edge-IDF holdouts. The tracked
  [ranking manifest](corpus/v0.4-ranking-holdout/holdout.json) has SHA-256
  `6fe09278638ccede6e4be981fcc8b2fd5fedcd9288dbcc780210032bce616736`. The tracked
  [edge-IDF manifest](corpus/v0.4-edge-idf-holdout/holdout.json) has SHA-256
  `1b45b645362a26a24e3d89805282b4dfd14c583b527ebe326698fbce4f0b5eaf`.
- Selection: each manifest's fixed primary node; ranking was not run
- Comparison: the full canonical one-hop edge set determined the affected tasks. The product review
  API's capped proposal set was measured separately for required-neighbor Recall@10 and the 10-item
  cap.
- Oracle: [oracle.json](oracle.json), frozen before result interpretation with SHA-256
  `39a617eab127040f6bfa4a1577dd1be04e4d0f11093ec2c40ffad41427a9b0f1`. Required and allowed
  neighbors were assigned from the prompts and reference patches by a reviewer who did not read
  either product output.
- Runtime: CPython 3.14.3. Baseline and current were each repeated with hash seeds 0 and 1 in
  `-S` workers.
- Measurement code: [frozen_evaluator.py](frozen_evaluator.py), preserved byte for byte from the
  original study with SHA-256
  `124d0e7e68c5a3352a47611ab0ea165a0373b3b832646f956d48035093238d78`.

The evaluator reads canonical source snapshots from regular Git blobs at each manifest commit, so a
checkout's symlink and line-ending policy cannot change the measured graph. It separately requires a
clean tracked worktree and rejects any collected Python file that is untracked or differs from its
HEAD blob. For the audit only, CRLF bytes are accepted when their sole normalization to LF matches the
blob exactly. Existing `.silobrief` files are not inputs; their complete path-and-byte digest, Git
status, and tracked-file digest must remain unchanged across all workers.

## Reproduce from a clean clone

Git and CPython 3.14.3 are required. The preparation step needs network access. The evaluator itself
uses only the prepared checkouts and Git objects.

```text
git clone https://github.com/d3vksy/silobrief.git
cd silobrief
python validation/v1.0-scope-related-context/prepare.py
python validation/v1.0-scope-related-context/evaluate.py --check
```

The preparation command fetches each commit listed below and checks it out in detached HEAD state.
It does not follow a branch or select the latest commit. Running the command again reuses a clean,
correct checkout. It stops if a checkout has local changes or a different origin URL.

| Suite | Repository URL | Commit | Checkout path |
| --- | --- | --- | --- |
| ranking | `https://github.com/encode/starlette.git` | `99b7cc62e0c2cb8d24e5f546b7e34e17496c265e` | `corpus/v0.4-ranking-holdout/repos/starlette` |
| ranking | `https://github.com/vitalik/django-ninja.git` | `134869b74b6cba214284faa9f13d54b7247362c0` | `corpus/v0.4-ranking-holdout/repos/django-ninja` |
| ranking | `https://github.com/litestar-org/litestar.git` | `ec6f9c95443d323a8cee4d9ff5dd1bd9862f5fc8` | `corpus/v0.4-ranking-holdout/repos/litestar` |
| ranking | `https://github.com/pallets/jinja.git` | `5ef70112a1ff19c05324ff889dd30405b1002044` | `corpus/v0.4-ranking-holdout/repos/jinja` |
| ranking | `https://github.com/pytest-dev/pytest.git` | `28e86a6c2ae0173831e4925a4af89b02a2936d09` | `corpus/v0.4-ranking-holdout/repos/pytest` |
| ranking | `https://github.com/python-poetry/poetry.git` | `92b74dcfe348d0e01e14d40d6c1fa47a4ee04a54` | `corpus/v0.4-ranking-holdout/repos/poetry` |
| edge-IDF | `https://github.com/pallets/flask.git` | `06ea505ce2b2042af26e96d35ebf159af7c0869d` | `corpus/v0.4-edge-idf-holdout/repos/flask` |
| edge-IDF | `https://github.com/aio-libs/aiohttp.git` | `0ed510d8dc9f6397878fe775ac7e2fbd0b13641f` | `corpus/v0.4-edge-idf-holdout/repos/aiohttp` |
| edge-IDF | `https://github.com/sanic-org/sanic.git` | `a64dc641a8e4ad777a4602d2bdec53d736901472` | `corpus/v0.4-edge-idf-holdout/repos/sanic` |
| edge-IDF | `https://github.com/Textualize/rich.git` | `9cb198944f8184df92217efc8b20d3fffa4b4fa0` | `corpus/v0.4-edge-idf-holdout/repos/rich` |
| edge-IDF | `https://github.com/psf/black.git` | `fa72105efac5c15c3a3c83c21ec6e6097c525325` | `corpus/v0.4-edge-idf-holdout/repos/black` |
| edge-IDF | `https://github.com/pydantic/pydantic.git` | `a54529f06204ecb8f940d2506ff66dd1521917c8` | `corpus/v0.4-edge-idf-holdout/repos/pydantic` |

The checkout paths are relative to `validation/v1.0-scope-related-context`. Git ignores the
downloaded repositories, but tracks both manifests. To put the corpus elsewhere, pass the same
`--external-root PATH` to `prepare.py` and `evaluate.py`.

The evaluator never clones, fetches, checks out, or writes an external repository. It checks the
commit and working tree before evaluation, then compares repository state after all workers finish.
The manual [Scope evaluator workflow](../../.github/workflows/scope-evaluator.yml) runs the same two
commands from a full-history checkout.

Successful verification prints:

```text
canonical_sha256=0c65bd3a7d64bc5218583b08c332029e384bda63bcd42337999c92ffd0171923
```

## Results

The canonical result is [results.json](results.json), SHA-256
`0c65bd3a7d64bc5218583b08c332029e384bda63bcd42337999c92ffd0171923`.

| Holdout | Observed change | Required related nodes | Static edges |
| --- | --- | ---: | ---: |
| `litestar-org/litestar` | Added the nested `send_wrapper` caller | 1/2 → 2/2 | 2/3 → 3/3 |
| `sanic-org/sanic` | Added the `StartupMixin.serve` caller | 0/1 → 1/1 | 1/2 → 2/2 |
| `psf/black` | Added the `calls` relation from `hug_power_op` to `is_simple_operand` | 0/2 → 0/2 | 7/8 → 8/8 |

Across the affected cases, required-neighbor recall rose from 1/5 to 3/5. The current graph recovered
all 13 statically resolvable oracle edges with no extra edge, so both edge precision and recall were
13/13. Required neighbors were never lost, the aggregate unnecessary proposal count stayed at 9,
and the related-context API never returned more than 10 items.

All automatic gates passed:

- affected tasks: 3, meeting the minimum of 3
- task-level improvements: 2, meeting the minimum of 2
- invalid current edges: 0
- boundary canary exposures: 0
- `setup_project` and `snapshot_sources` control proposal sets: unchanged
- seed and input-order determinism: passed
- frozen external inputs and post-run repository state: unchanged

The Black task still lacks `Line.append` and `Leaf.clone`. Those calls use dynamically resolved
receivers, so the current static graph cannot identify their concrete types. This is an explicit
limit of the experiment, not evidence that the lexical-scope fix regressed the task. The oracle was
checked against [Litestar PR 3776](https://github.com/litestar-org/litestar/pull/3776),
[Sanic PR 3122](https://github.com/sanic-org/sanic/pull/3122) and reference fix `dc0939e`, and
[Black PR 5272](https://github.com/psf/black/pull/5272) and reference fix `006b2a7` before the
generated result was interpreted.

## Verification

Run from the repository root:

```text
python validation/v1.0-scope-related-context/prepare.py
python validation/v1.0-scope-related-context/evaluate.py --check
python -m unittest tests.test_scope_evaluator
python -m unittest tests.test_index tests.test_boundary_placeholders tests.test_source_review tests.test_python_structure
```

The first command prepares only the pinned inputs. The second independently recomputes the result
and compares it with [results.json](results.json). The original focused lexical-scope and boundary
regression gate ran 64 tests successfully. The complete study test suite also passed 234 tests with
7 expected skips, and Ruff reported no findings.

## Not now

Do not add a graph database, LLM ranking, multi-hop traversal, or receiver-type inference as part of
this work. Receiver inference may be studied later with its own narrow corpus and stop criteria if
the missing Black neighbors prove important in more than this one task.
