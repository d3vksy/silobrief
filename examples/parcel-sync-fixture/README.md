# parcel-sync fixture

This is a synthetic Python project for the public siloBrief demo. It contains no real
organization, repository, or operational data. Run the demo on a disposable copy because
the commands create a local `.silobrief/` directory.

The allowed package imports `urllib3` as documentation context and references a separately
provided adapter. The adapter directory is registered as a boundary before indexing. The
source also contains known canaries used only to verify what the generated brief omits.

From the fixture root, run:

```text
sb setup .
sb ignore private_adapter --as "External delivery adapter" --alias delivery-boundary
sb init
sb log src/parcel_sync/service.py --comment "HTTP 503 responses may be retried."
sb chat "retry request" --out .silobrief/exports/retry-brief.md
```

For the bundled fixture, confirm request completeness with `y`, select candidate `1`, and
finish both add and exclude prompts with a blank line. Answer `y` to each of the five context
questions. The complete `retry_request` excerpt is then shown; review it before answering `y`.
Because that excerpt contains a boundary reference, type exactly `EXPOSE`. Review both full
Markdown previews and type exactly `WRITE` to create `retry-brief.md` and
`retry-brief.sources.md`.

The main brief includes the relative service path, `retry_request`, `urllib3`, the human note,
and the `delivery-boundary` description. The companion includes only the approved function
excerpt, including its visible boundary call after `EXPOSE`. Neither file may include the
ignored adapter source or private canary. This verifies the published technical contract only;
it is not a security certification or evidence of user demand. siloBrief does not detect
secrets in allowed source, so both previews require a human disclosure decision.
