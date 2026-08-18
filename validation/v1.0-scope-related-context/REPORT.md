# Scope-related one-hop context validation

## Decision

Proceed with the lexical-scope correction. The fixed-primary comparison affected three of the 12
holdout tasks, met every gate in Issue #185, and improved the required related context in two cases.
This result supports the scope fix only; it does not justify a graph database, multi-hop expansion,
or an LLM-based retrieval layer.

## Frozen protocol

- Baseline: `e5329b29d884d40dc7d3b14ca7fa26c83a14878b`
- Current: `ab98e39910d9dc70eacdad3fcb4df4d5e7b579de`
- Corpus: the six v0.4 ranking holdouts and six v0.4 edge-IDF holdouts
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

The evaluator reads canonical source snapshots from regular Git blobs at each manifest commit, so a
checkout's symlink and line-ending policy cannot change the measured graph. It separately requires a
clean tracked worktree and rejects any collected Python file that is untracked or differs from its
HEAD blob. For the audit only, CRLF bytes are accepted when their sole normalization to LF matches the
blob exactly. Existing `.silobrief` files are not inputs; their complete path-and-byte digest, Git
status, and tracked-file digest must remain unchanged across all workers.

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
python validation/v1.0-scope-related-context/evaluate.py
python validation/v1.0-scope-related-context/evaluate.py --check
python -m unittest tests.test_index tests.test_boundary_placeholders tests.test_source_review tests.test_python_structure
```

The first command wrote the canonical result. The second independently recomputed it and returned
the same SHA-256. The focused lexical-scope and boundary regression gate ran 64 tests successfully.
The complete test suite also passed 234 tests with 7 expected skips, and Ruff reported no findings.

## Not now

Do not add a graph database, LLM ranking, multi-hop traversal, or receiver-type inference as part of
this work. Receiver inference may be studied later with its own narrow corpus and stop criteria if
the missing Black neighbors prove important in more than this one task.
