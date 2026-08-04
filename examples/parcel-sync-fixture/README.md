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

For the bundled fixture, select candidate `1`, finish both add and exclude prompts with a
blank line, answer `y` to each of the five disclosure questions, review the complete
Markdown preview, and type exactly `WRITE` to create the file.

The expected brief includes the relative service path, `retry_request`, `urllib3`, the human
note, and the `delivery-boundary` description. It must not include the adapter's real path,
symbol, or private canary. This verifies the published technical contract only; it is not a
security certification or evidence of user demand.
