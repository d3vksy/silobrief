# v0.7 retrieval result

Date: 2026-08-11

Status: PASS on Windows and local WSL2 Ubuntu; hosted CI is pending a pushed revision.

## Decision

Ship the narrow lexical-ranking improvement toward 1.0. Do not add recursive graph retrieval or
an embedding/vector dependency. The current improvement clears the predeclared gate while reducing
irrelevant candidates and preserving the boundary canary.

## Frozen benchmark

The benchmark is implemented in `tests/test_graph_retrieval_baseline.py`. It contains 12 fixed
maintenance tasks and 17 expected symbols across this repository and the public model-validation
fixture. It builds indexes through the production source snapshot and indexer and compares only
stable path and qualified-symbol values.

- repository corpus digest: `913ce7824c3ad60fd63f022b7f8c35e815b76d973aa6945aed8d9522a5ebd79b`
- fixture corpus digest: `39bad3c745e233443def7665189d5518d48852bc5b1d2857b3ddb5970ed5568f`
- boundary canary disclosures: 0

## Results

| Metric | v0.6 behavior | Current | Gate |
|---|---:|---:|---:|
| Tasks with an expected symbol in the returned candidates | 4/12 (33.3%) | 11/12 (91.7%) | >= 80% |
| Expected symbols returned | 5/17 (29.4%) | 14/17 (82.4%) | diagnostic |
| Mean reciprocal rank | 37/168 (22.0%) | 13/18 (72.2%) | >= 0.50 |
| Irrelevant returned candidates | 85 | 44 | lower is better |
| Maximum proposed one-hop context | 12 | 10 | <= 10 |
| Registered-boundary canary disclosures | 0 | 0 | 0 |

The current reciprocal-rank sum is `26/3` over 12 tasks. Normal prompts return at most seven
implementation candidates. A prompt must explicitly mention testing to receive a bounded test-file
quota. Import tokens remain explainable tie-breaking evidence but cannot make an import-only node a
candidate.

## Reproduction

```powershell
$env:PYTHONPATH='src'
python -m unittest tests.test_graph_retrieval_baseline -v
python tests/test_graph_retrieval_baseline.py
```

The second command prints canonical JSON for independent comparison. On Windows and WSL2 Ubuntu
with Python 3.12.3, the complete canonical JSON was identical; the shared comparison SHA-256 was
`08b4f3816ebe535de5e7931e7904b2612237827ed968cd4c88ae8534019f1314`. The hosted repository CI
matrix remains pending until the revision is pushed.

## Limits

This is a small synthetic/repository benchmark, not evidence of broad user demand or superiority to
manual context selection. One of 12 tasks still misses, and 3 of 17 expected supporting symbols are
not returned. Those limitations are preferable to widening retrieval with unbounded graph noise.
