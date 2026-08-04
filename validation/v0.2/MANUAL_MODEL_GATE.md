# siloBrief v0.2 manual model gate

Status: `READY FOR MANUAL MODEL TEST`

Installed-wheel evidence: [`INSTALLED_WHEEL_VERIFICATION.md`](INSTALLED_WHEEL_VERIFICATION.md)

This gate evaluates whether an external model can produce an actionable maintenance answer from
the two files created by siloBrief. It does not validate security, market demand, or general model
quality. The fixture is synthetic. Do not send this evaluator guide to a model.

## Frozen tasks

### T01-MODIFY

Prompt:

> Update the retry policy in src/parcel_lab/retry.py so status-code retries apply to HTTP 503 and
> not HTTP 500. Keep total=2 and preserve the delivery boundary call order. Return a minimal patch
> and focused unittest. Do not claim you ran tests.

Public note: `urllib3 version is 2.7.0.`

Selection: candidate `2`; no manual add or exclusion; approve all five context fields; approve the
single source excerpt; type `EXPOSE`; approve both outputs with `WRITE`.

Model inputs:

- `packets/T01-MODIFY/t01-modify.md`
- `packets/T01-MODIFY/t01-modify.sources.md`

### T02-ADD

Prompt:

> Add an optional separator: str setting to LabelOptions. Existing callers that omit it must keep
> current output. When both prefix and separator are non-empty, place the separator between prefix
> and reference. Preserve uppercase behavior. Return a minimal patch and focused unittests.

Selection: candidates `1 2`; no manual add or exclusion; approve all five context fields; approve
both source excerpts; approve both outputs with `WRITE`.

Model inputs:

- `packets/T02-ADD/t02-add.md`
- `packets/T02-ADD/t02-add.sources.md`

### T03-REMOVE

Prompt:

> Remove the legacy fallback from choose_reference. The function must accept only primary, return
> its stripped value, and raise ValueError when it is blank. Return a minimal patch and focused
> unittests. State the interface impact without inventing call sites.

Selection: candidate `1`; no manual add or exclusion; approve all five context fields; approve the
single source excerpt; approve both outputs with `WRITE`.

Model inputs:

- `packets/T03-REMOVE/t03-remove.md`
- `packets/T03-REMOVE/t03-remove.sources.md`

## Frozen packet SHA-256

| File | SHA-256 |
|---|---|
| `T01-MODIFY/t01-modify.md` | `0ef829e88a240c29ec62b0281015abec48b6f1b7476ada412059cdfef140dd30` |
| `T01-MODIFY/t01-modify.sources.md` | `26e81597f2edd4c65f226ddafc4a291e595e5fb75f5a133d5136ca94d106e698` |
| `T02-ADD/t02-add.md` | `55bee4ae3e5e34f3570c908d88227d8c181b497db916def96669552b6826c744` |
| `T02-ADD/t02-add.sources.md` | `7deb0e384fbf625f295ade605d6cb1da2d2bc4a9c68ebe83c6fb4e46b4ed6574` |
| `T03-REMOVE/t03-remove.md` | `75fb9d63c0023a3afee3132b2740b308db9ed5cf68cea5087ea890630acb83ce` |
| `T03-REMOVE/t03-remove.sources.md` | `4ad9d025d2027cc569499a0d42cbdaf6b0b650c5cc6cce09c0bbe74c0aa9c597` |

## Model procedure

Run the six trials in fresh chats: three with GPT and three with Claude. For each trial, attach only
the task's main and source companion files. Do not paste this guide, add an explanation, answer a
clarifying question, or provide a follow-up hint. Record the model and mode exactly as shown by the
service.

## Pass criteria

A response passes only if all of these are true:

- the target file and change purpose are clear within 30 seconds;
- public fields, function signatures, and control flow are preserved unless the task changes them;
- hidden implementation is not presented as fact;
- an applicable patch or complete replacement is present;
- focused behavior tests are present;
- tests that were not run are not described as having passed.

Any ignored source content in a packet is a fatal packet failure. A model passes the release gate
only with at least two passing tasks out of three. Both GPT and Claude must independently pass. Keep
the raw responses and failures; do not revise prompts, thresholds, or packets after the first trial.
