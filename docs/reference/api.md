# pdf2epub API reference

pdf2epub has two interfaces for programs: the `--json` wire protocol of the `pdf2epub` command, and the Python API of the `pdf2epub` package. The normative definitions are in the [API spec](../specs/api.md).

## Stability

The `--json` protocol is the stable contract: the JSON Lines event stream on stdout and the `--report` file. Front ends should drive the `pdf2epub` command and read that protocol.

The Python API is provisional: it may change in any 0.x release. Embed it only if you accept that.

## The `--json` protocol

`pdf2epub --json INPUT...` writes one JSON object per line to stdout, from `batch_started` to `batch_finished`; nothing else is written to stdout. Every event carries `v` (the protocol version, `1`), `type` and `t` (seconds since the batch started). Logging goes to stderr only, at INFO with `-v` and at DEBUG with `--debug`.

`--report FILE` writes the `batch_finished` event to `FILE`, byte for byte as its `--json` line, in human mode as well as in `--json` mode.

The JSON Schema (draft 2020-12) for v1 events ships inside the package at `pdf2epub/schema/events.v1.json`:

```python
from importlib import resources

schema = (resources.files("pdf2epub") / "schema" / "events.v1.json").read_text()
```

Additive changes (new fields, event types, issue codes or reasons) keep `v` at `1`, so ignore fields and event types you don't know, and handle an unknown issue code by its `severity`.

## The Python API (provisional)

```python
from pdf2epub import (
    BatchOptions, ConversionOptions, DiscoveryOptions, InputSpec, plan_batch, run_batch,
)

plan = plan_batch([InputSpec("book.pdf")], DiscoveryOptions())
report = run_batch(plan, BatchOptions(), ConversionOptions(), sink=print)
```

`plan_batch` plans the conversions without converting anything. `run_batch` runs them synchronously, passes every event (a `dict`, the same object as its `--json` line) to `sink` from the calling thread, and returns the `BatchReport`, whose `to_dict()` is the `batch_finished` payload without the envelope fields.
