# Small field-trial procedure

Status: ready to run; no participant result is claimed

This trial is deliberately usable by one developer. It compares siloBrief with the developer's
normal manual context-packet workflow rather than requiring recruited users.

## Tasks

Choose three bounded Python maintenance tasks that can each be checked in under 30 minutes:

1. modify one existing behavior;
2. add one small behavior; and
3. remove one obsolete behavior.

Do not use a task whose solution is already visible in a previous AI conversation. Record the task,
required deliverable, and acceptance criteria before preparing either packet.

## Comparison

For each task, prepare two packets without editing source:

- A: the normal manual selection/copy method;
- B: `sb search` followed by `sb brief`.

Alternate which method is prepared first. Record preparation minutes, wrong or missing target
symbols, number of context items removed during review, and final UTF-8 bytes. Send each packet to
the same external model with a fresh conversation and unchanged prompt. Save the raw answers under
a private trial directory outside the repository.

On the following day, hide the method labels and score each answer:

- required behavior addressed: yes/no;
- patch uses only supplied context: yes/no;
- tests cover the acceptance criteria: yes/no;
- unsafe or invented project detail: yes/no;
- usable with at most minor correction: yes/no.

## Decision rule

Continue the product claim only if siloBrief finds the intended primary symbol in all three tasks,
discloses no unapproved item, and produces at least two usable answers without taking more than 25%
longer than the manual median. Otherwise keep the boundary-review utility but narrow the retrieval
or productivity claim.

Three self-evaluated tasks are directional evidence, not market validation. Record negative results
unchanged instead of tuning the rule after seeing them.
