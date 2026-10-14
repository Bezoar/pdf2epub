# Core API and wire protocol

**Status:** draft · **Depends on:** [main](main.md), [batch](batch.md), [passwords](passwords.md), [reflow](reflow.md), [ocr](ocr.md) · **Decisions:** [Front-end integration patterns for the core](https://github.com/Bezoar/pdf2epub/issues/4), [Core API shape for front ends](https://github.com/Bezoar/pdf2epub/issues/10), [Batch mode semantics and end-of-batch report](https://github.com/Bezoar/pdf2epub/issues/9), [OCR engine interface design](https://github.com/Bezoar/pdf2epub/issues/13), [Text-layer quality check](https://github.com/Bezoar/pdf2epub/issues/15), [ADR 0001](../adr/0001-python-core.md)

This spec owns the **contract** every front end builds on: the Python entry points, the event stream and its JSON Lines encoding (`--json`), the `--report` file, the issue-code registry, outcomes, results, options *shape*, the password-provider protocol, cancellation, versioning and the JSON Schema. It does **not** own the rules for when an issue fires or which outcome a situation produces; each registry entry links to the spec that does. Option *meanings and defaults* belong to the owning specs ([batch](batch.md), [reflow](reflow.md), [ocr](ocr.md), [passwords](passwords.md)); flag names belong to [cli](cli.md).

## 1. Contracts and stability

<a id="api-r1"></a>**API-R1**: The `--json` wire protocol (the JSON Lines event stream on stdout and the `--report` file) shall be the only **stable** public contract. The Python API (`import pdf2epub`) shall be documented but **provisional**: it may change in any 0.x release.

Front ends (the CLI first, later GUIs) drive the CLI as a subprocess and read the wire protocol ([ADR 0001](../adr/0001-python-core.md)). A GUI that embeds Python may call the Python API directly, accepting that it is provisional.

## 2. Entry points

```python
def plan_batch(inputs: Sequence[InputSpec], options: DiscoveryOptions) -> BatchPlan: ...

def run_batch(
    plan: BatchPlan,
    batch_options: BatchOptions,
    conversion_options: ConversionOptions,
    sink: EventSink,
    cancel: CancelToken | None = None,
    passwords: PasswordProvider | None = None,
) -> BatchReport: ...

EventSink = Callable[[Event], None]
```

<a id="api-r2"></a>**API-R2**: `plan_batch` shall turn the raw inputs (positional paths and the lines of a files-from list) into a `BatchPlan` without converting anything. It applies every discovery rule in [batch §1–§3](batch.md#1-inputs): folder expansion, recursion, magic-byte checks, de-duplication, ordering, output mapping, `output_collision` and `output_exists`. Each `PlannedConversion` carries `id` (its 0-based index in the plan), the absolute `source`, the absolute `destination` (or `null` when none applies, e.g. `not_found`), and any planning issues.

<a id="api-r3"></a>**API-R3**: `run_batch` shall be **synchronous and blocking**. It runs every planned conversion, pushes each event to `sink` as it happens, and returns the `BatchReport`. There is no asyncio API; a GUI that embeds Python runs `run_batch` on a thread of its own.

<a id="api-r4"></a>**API-R4**: The core shall call `sink` from **one thread only**, the thread that called `run_batch`, so sinks never need to be thread-safe. The `--json` writer and the human reporter in the CLI are both plain sinks.

<a id="api-r5"></a>**API-R5**: `BatchOptions.isolation` shall select where conversions run: `"subprocess"` (the default, and the only mode the CLI uses) or `"inprocess"` (for tests and embedders). Both modes shall produce the same events, outcomes and issue codes for any input that neither crashes nor exceeds its timeout; only crash and timeout containment differ ([batch §5](batch.md#5-isolation-and-timeouts)).

## 3. Cancellation

```python
class CancelToken:
    def cancel(self) -> None: ...
    @property
    def cancelled(self) -> bool: ...
```

<a id="api-r6"></a>**API-R6**: `CancelToken.cancel()` shall be safe to call from any thread or a signal handler. Once it is set, `run_batch` shall stop as defined in [batch §4](batch.md#4-resume-and-interrupt) and return a `BatchReport` with `interrupted = true` and `exit_code = 130`.

Over the wire, cancellation is SIGINT or SIGTERM to the CLI process, or the `cancel` stdin message in `--interactive` mode ([§10](#10-stdin-messages---interactive)).

## 4. Passwords

```python
class Secret:            # wraps one password value
    def reveal(self) -> str: ...
    # __str__ and __repr__ return "***"; JSON encoding raises TypeError

SourceLabel = str        # e.g. 'map:"statements/*.pdf"', 'env', 'file:line 3', 'cli #2', 'prompt'

class Candidate(NamedTuple):
    secret: Secret
    source: SourceLabel

class PasswordProvider(Protocol):
    def candidates(self, path: Path) -> list[Candidate]: ...
    # None when this provider cannot prompt:
    prompt: Callable[[Path, int], Secret | None] | None
```

<a id="api-r7"></a>**API-R7**: The core shall obtain candidate passwords only through a `PasswordProvider`. `candidates(path)` returns the candidate passwords for one file, each with its password source label. `prompt` is an attribute holding either a function `(path, attempt) -> Secret | None` or `None`; when it is `None`, or the run is not allowed to prompt, the core emits `password_required` and skips the file as defined in [passwords](passwords.md). The trial order, the 25-candidate cap, the owner-password retry and prompt deferral are core rules owned by [passwords](passwords.md); the core ships the standard provider that builds candidates from the user's password sources ([passwords: `SourcePasswordProvider`](passwords.md)).

<a id="api-r8"></a>**API-R8**: Every password value inside the core shall be held as a `Secret`. `str()` and `repr()` of a `Secret` shall return `***`; JSON encoding of a `Secret` (by the standard `json` module and by the event writer) shall raise `TypeError`; the value is reachable only through `reveal()`. No event, issue, result, report or log record shall carry a password value; reports name only the password source label.

## 5. Options

<a id="api-r9"></a>**API-R9**: Options shall be **frozen dataclasses** of plain data. Defaults shall be defined only in the core; front ends (the CLI included) pass a field only when the user set it and never restate a default.

| Class | Fields | Owner of meaning and defaults |
|---|---|---|
| `DiscoveryOptions` | `recursive`, `output` | [batch §6](batch.md#6-options) |
| `BatchOptions` | `timeout`, `overwrite`, `isolation`, `strict` | [batch §6](batch.md#6-options) |
| `ConversionOptions` | `mode`, `language`, `title`, `authors`, `cover`, `ocr: OcrOptions` | [reflow](reflow.md) (all but `ocr`) |
| `OcrOptions` | `mode`, `languages`, `quality`, `page_timeout`, `min_confidence`, `engine_options`, `tesseract_path`, `tessdata_dir` | [ocr](ocr.md) |
| `PasswordSources` | `map_file`, `values`, `env_value`, `password_file`, `prompt` | [passwords](passwords.md) |

v1 has no general configuration file; the password map is the only file of settings ([roadmap](../worksheets/roadmap.md)).

## 6. Issues and outcomes

```python
class Severity(StrEnum): ERROR = "error"; WARNING = "warning"; INFO = "info"
class Outcome(StrEnum):  CONVERTED = "converted"; SKIPPED = "skipped"; FAILED = "failed"

@dataclass(frozen=True)
class Issue:
    code: IssueCode
    severity: Severity        # always IssueCode's fixed severity
    pages: list[int]          # 1-based PDF page numbers, ascending; [] for conversion-level issues
    reason: str | None        # sub-kind, e.g. page_fallback "complex"
    message: str              # one sentence for a person
    hint: str | None          # one-line fix suggestion, if any
```

<a id="api-r10"></a>**API-R10**: `IssueCode` shall be an enum whose members are exactly the codes in the registry below. Each code's **severity is fixed** by the registry; no issue instance overrides it.

<a id="api-r11"></a>**API-R11**: Page-level issues shall be grouped into **one issue per (code, reason)** per conversion, with an ascending, duplicate-free page list. Every page that ends as a page image shall appear in exactly one `page_fallback` issue. Conversion-level issues have an empty page list.

<a id="api-r12"></a>**API-R12**: A conversion's **outcome** shall be derived from its issues, in this order:
1. any issue with severity `error` ⇒ `failed`;
2. otherwise any of `output_exists`, `output_collision`, `not_attempted` ⇒ `skipped`;
3. otherwise ⇒ `converted`.

### 6.1 Issue-code registry

Codes are lower-case snake case. *Reason* lists the allowed `reason` values (otherwise `reason` is `null`). The rule owner is the spec that says when the code fires.

| Code | Severity | Reason | Meaning | Rule owner |
|---|---|---|---|---|
| <a id="code-missing_password"></a>`missing_password` | error | — | The file is a password-protected PDF and no candidate password other than the empty one was available (or the prompt was skipped). | [passwords](passwords.md) |
| <a id="code-wrong_password"></a>`wrong_password` | error | — | Candidate passwords were tried and none opened the file. The message lists the password sources tried, never values. | [passwords](passwords.md) |
| <a id="code-restricted"></a>`restricted` | error | — | The file opened, but its permission restrictions forbid copying or extracting content and no candidate was its owner password. No EPUB is written. Hint: supply the owner password. | [passwords](passwords.md) |
| <a id="code-drm_protected"></a>`drm_protected` | error | — | The file is DRM-protected (a security handler other than the standard password scheme, or a vendor wrapper). Refused by design. Hint: open it in the vendor's reader; pdf2epub will not bypass DRM. | [passwords](passwords.md) |
| <a id="code-unsupported_encryption"></a>`unsupported_encryption` | error | — | The file uses the standard password scheme with a revision or algorithm outside the supported set. | [passwords](passwords.md) |
| <a id="code-owner_password_used"></a>`owner_password_used` | info | — | The file had permission restrictions and was converted using its owner password; the message names the password source. | [passwords](passwords.md) |
| <a id="code-not_found"></a>`not_found` | error | — | An input path does not exist or cannot be read. | [batch](batch.md) |
| <a id="code-not_a_pdf"></a>`not_a_pdf` | error | — | An explicitly named input is not a PDF by content. | [batch](batch.md) |
| <a id="code-corrupt_pdf"></a>`corrupt_pdf` | error | — | The PDF cannot be parsed even with repair. | [reflow](reflow.md) |
| <a id="code-repaired_pdf"></a>`repaired_pdf` | warning | — | The parser recovered from damage in the file; output may be incomplete. | [reflow](reflow.md) |
| <a id="code-empty_document"></a>`empty_document` | error | — | The PDF has no pages, or no page yields any text or image. | [reflow](reflow.md) |
| <a id="code-resource_limit"></a>`resource_limit` | error | — | The file exceeded a safety limit for untrusted input (e.g. an image decompression bomb). | [reflow](reflow.md) |
| <a id="code-output_exists"></a>`output_exists` | info | — | The destination EPUB already exists and overwriting was not requested. Outcome `skipped`. | [batch](batch.md) |
| <a id="code-output_collision"></a>`output_collision` | info | — | An earlier conversion in the same batch maps to the same destination. Outcome `skipped`. | [batch](batch.md) |
| <a id="code-write_failed"></a>`write_failed` | error | — | The EPUB could not be written to its destination. | [batch](batch.md) |
| <a id="code-page_fallback"></a>`page_fallback` | warning | `complex`, `multi_column` ([reflow](reflow.md)); `ocr_low_confidence`, `bad_text_layer`, `ocr_failed`, `ocr_timeout`, `ocr_unavailable` ([ocr](ocr.md)) | The listed pages were embedded as page images with hidden searchable text instead of being reflowed. | [reflow](reflow.md), [ocr](ocr.md) |
| <a id="code-language_defaulted"></a>`language_defaulted` | warning | — | No language was given or found; the book was labelled `en`. | [reflow](reflow.md) |
| <a id="code-page_sequence_gap"></a>`page_sequence_gap` | warning | — | The printed page numbers skip or repeat, suggesting a page was not scanned or was scanned twice. The pages listed are the PDF pages on either side of each break. | [reflow](reflow.md) |
| <a id="code-ocr_unavailable"></a>`ocr_unavailable` | warning | — | Pages needed OCR but Tesseract or its language data is missing; those pages fell back. Conversion-level, with an install hint. | [ocr](ocr.md) |
| <a id="code-ocr_timeout"></a>`ocr_timeout` | warning | — | OCR on the listed pages exceeded the per-page budget; those pages fell back. | [ocr](ocr.md) |
| <a id="code-ocr_failed"></a>`ocr_failed` | warning | — | The OCR engine crashed or exited with an error on the listed pages; those pages fell back. | [ocr](ocr.md) |
| <a id="code-text_layer_rejected"></a>`text_layer_rejected` | info | `garbled`, `implausible_words`, `low_coverage` | The existing text layer of the listed pages failed the text-layer quality check. | [ocr](ocr.md) |
| <a id="code-not_attempted"></a>`not_attempted` | info | — | The batch was interrupted before this conversion finished. Outcome `skipped`. | [batch](batch.md) |
| <a id="code-timeout"></a>`timeout` | error | — | The conversion exceeded its time limit and was stopped. | [batch](batch.md) |
| <a id="code-internal_error"></a>`internal_error` | error | — | pdf2epub failed unexpectedly (crash or bug). Message ends with "please report this bug". | [batch](batch.md) |

## 7. Results

```python
@dataclass(frozen=True)
class OcrSummary:
    engine: str               # "tesseract"
    engine_version: str
    languages: list[str]      # engine language codes actually used
    quality: str              # "fast" | "balanced" | "best"

@dataclass(frozen=True)
class ConversionResult:
    id: int
    source: str               # absolute path
    destination: str | None   # absolute path the EPUB maps to
    outcome: Outcome
    issues: list[Issue]
    output: str | None        # absolute path of the EPUB written, else None
    password_source: str | None   # source label that opened the file, else None
    pages: int | None         # PDF page count, None if never opened
    duration: float           # seconds
    ocr: OcrSummary | None    # None when the conversion ran no OCR

@dataclass(frozen=True)
class BatchReport:
    tool_version: str
    started_at: str           # ISO-8601 UTC, e.g. "2026-10-13T09:15:02Z"
    conversions: list[ConversionResult]   # input (plan) order
    totals: Totals            # converted, skipped, failed
    interrupted: bool
    exit_code: int
```

<a id="api-r13"></a>**API-R13**: `ConversionResult` shall carry exactly the fields above. `output` is set only when an EPUB was written by this run. `ocr` is `null` when the conversion ran no OCR attempt.

<a id="api-r14"></a>**API-R14**: `BatchReport.conversions` shall list conversions in **plan order**, whatever order they finished in, and `totals` shall count each outcome. `exit_code` follows [batch §7](batch.md#7-exit-codes).

<a id="api-r15"></a>**API-R15**: Every path in events, results and the report shall be **absolute**.

## 8. Event stream

<a id="api-r16"></a>**API-R16**: Every event shall carry `v` (protocol version, `1`), `type`, and `t` (seconds since the batch started, from a monotonic clock, non-decreasing across the stream). Every conversion-scoped event shall also carry `id`, the conversion's index in the plan.

<a id="api-r17"></a>**API-R17**: The v1 event catalogue shall be:

| `type` | Fields (besides `v`, `type`, `t`) | When |
|---|---|---|
| `batch_started` | `tool_version`, `total`, `jobs` (always `1` in v1), `planned: [{id, source, destination}]` | First event of every run that passes the usage checks; a usage error emits no events at all ([batch](batch.md#bat-r25)). |
| `conversion_started` | `id` | A planned conversion begins work. |
| `progress` | `id`, `stage`, `done`, `of`, plus stage fields ([§9](#9-progress)) | During a conversion. |
| `issue` | `id` (`null` = batch-level), `issue` (an Issue) | As soon as an issue is known; the same issue also appears in `conversion_finished`. |
| `password_required` | `id`, `sources_tried` (source labels only) | A password is needed and cannot be asked for now; the file is skipped and reported `missing_password`, `wrong_password`, or `restricted` (when only the owner password is missing). |
| `password_request` | `id`, `request_id`, `attempt` (1–3) | `--interactive` only; answered on stdin ([§10](#10-stdin-messages---interactive)). |
| `conversion_finished` | `id`, `source`, `destination`, `outcome`, `output`, `issues`, `password_source`, `pages`, `duration`, `ocr` | A conversion ends, whatever its outcome. |
| `batch_finished` | `tool_version`, `started_at`, `totals {converted, skipped, failed}`, `interrupted`, `exit_code`, `conversions` (ConversionResult list, plan order) | Last event of every run that emitted `batch_started`. |

<a id="api-r18"></a>**API-R18**: Conversions whose fate is settled at planning time (`not_found`, `not_a_pdf`, `output_exists`, `output_collision`) shall be reported as `conversion_finished` events immediately after `batch_started`, in plan order, before any `conversion_started`. They get no `conversion_started` event.

<a id="api-r19"></a>**API-R19**: The `batch_finished` event shall be the serialised `BatchReport` (its fields, by the same names) wrapped in the common event envelope `v`, `type` and `t`. `BatchReport` itself carries no envelope fields. The `--report FILE` output shall be byte-for-byte the JSON object of that event (one object, UTF-8, with a trailing newline).

<a id="api-r20"></a>**API-R20**: In `--json` mode, stdout shall carry only events: one JSON object per line, UTF-8, with no blank lines, flushed after each event. Nothing else (logs, progress bars, the human report) shall be written to stdout.

## 9. Progress

<a id="api-r21"></a>**API-R21**: A conversion shall pass through the stages `open` (decrypt and classify), `analyse`, `ocr` (only pages that need OCR), `reflow` and `write`, in that order. `analyse` and `ocr` shall emit one `progress` event per page (`done` = pages finished so far in that stage, `of` = pages in that stage, `page` = 1-based PDF page number); `open`, `reflow` and `write` shall emit one event each with `done = of = 1`. A conversion that needs no OCR emits no `ocr` events. The core does not throttle events and gives no overall percentage; front ends weight the stages themselves.

<a id="api-r22"></a>**API-R22**: Each `progress` event of stage `ocr` shall also carry:
- `trigger`: `no_text_layer`, `text_layer_rejected` or `forced` (`forced` = OCR mode `always`), as defined in [ocr](ocr.md);
- `confidence`: page confidence of the kept attempt, in [0, 1];
- `coverage`: coverage of the kept attempt, in [0, 1];
- `attempts`: number of OCR attempts run on the page;
- `fell_back`: `true` if the page became a page image.

When no attempt produced a result (engine missing, crash or timeout on every attempt), `confidence` and `coverage` are `null`.

## 10. stdin messages (`--interactive`)

In `--json --interactive` mode the CLI reads JSON Lines from stdin while the batch runs.

| Message | Meaning |
|---|---|
| `{"type":"password","request_id":"…","password":"…"}` | Answer to a `password_request`. |
| `{"type":"password","request_id":"…","password":null}` | Skip this file (reported `missing_password`). |
| `{"type":"cancel"}` | Cancel the batch, as SIGINT does. |

<a id="api-r23"></a>**API-R23**: In `--json --interactive` mode, the CLI shall accept the stdin messages above. A `password` message answers the `password_request` with the same `request_id`; its value becomes a `Secret` labelled `prompt` immediately on reading. A `cancel` message cancels the batch. Lines that are not valid JSON, or have an unknown `type` or `request_id`, shall be ignored with a debug log on stderr. End of stdin while a request is pending counts as `password: null`.

## 11. Versioning and schema

<a id="api-r24"></a>**API-R24**: **Additive** changes (new fields, new event types, new issue codes, new `reason` values) shall not change `v`. Consumers must ignore unknown fields and unknown event types, and must handle an unknown issue code by its `severity`.

<a id="api-r25"></a>**API-R25**: **Breaking** changes (removing or renaming an event, field or code, or changing what one means) shall increase `v`.

<a id="api-r26"></a>**API-R26**: A JSON Schema (draft 2020-12) for v1 events shall ship inside the package at `src/pdf2epub/schema/events.v1.json`. It is authoritative for **shape**; this spec's prose is authoritative for **meaning**. Every event the core emits, and every `--report` file, shall validate against it. An event of a known `type` must match that type's definition. An event of an unknown `type` (an additive type from a later release, [API-R24](#api-r24)) validates against the envelope alone, so additions never require a new schema version. Until the build creates the file, the draft in [§13](#13-json-schema-draft) is the reference.

## 12. Design rules for parallel conversions and diagnostics

Parallel conversions (`-j`) are on the [roadmap](../worksheets/roadmap.md). v1 must not foreclose them.

<a id="api-r27"></a>**API-R27**: No event, result or sink contract shall assume a single "current conversion": every conversion-scoped event carries `id` ([API-R16](#api-r16)), sinks are called from one thread ([API-R4](#api-r4)), and the report is in plan order ([API-R14](#api-r14)). `batch_started.jobs` shall be `1` in v1.

<a id="api-r28"></a>**API-R28**: Free-text diagnostics shall go through Python `logging` to stderr only (shown with `-v` or `--debug`), and shall never be events. Anything a user must act on shall be an issue.

## 13. JSON Schema (draft)

Inline draft of `events.v1.json`. Shape only; `additionalProperties` stays open so additive changes validate.

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://github.com/Bezoar/pdf2epub/schema/events.v1.json",
  "title": "pdf2epub event (protocol v1)",
  "type": "object",
  "required": ["v", "type", "t"],
  "properties": {
    "v": {"const": 1},
    "type": {"type": "string"},
    "t": {"type": "number", "minimum": 0}
  },
  "oneOf": [
    {"$ref": "#/$defs/batch_started"},
    {"$ref": "#/$defs/conversion_started"},
    {"$ref": "#/$defs/progress"},
    {"$ref": "#/$defs/issue_event"},
    {"$ref": "#/$defs/password_required"},
    {"$ref": "#/$defs/password_request"},
    {"$ref": "#/$defs/conversion_finished"},
    {"$ref": "#/$defs/batch_finished"},
    {"properties": {"type": {"not": {"enum": ["batch_started", "conversion_started", "progress", "issue", "password_required", "password_request", "conversion_finished", "batch_finished"]}}}}
  ],
  "$defs": {
    "id": {"type": "integer", "minimum": 0},
    "abspath": {"type": "string", "pattern": "^(/|[A-Za-z]:\\\\)"},
    "severity": {"enum": ["error", "warning", "info"]},
    "outcome": {"enum": ["converted", "skipped", "failed"]},
    "issue": {
      "type": "object",
      "required": ["code", "severity", "pages", "reason", "message", "hint"],
      "properties": {
        "code": {"type": "string", "pattern": "^[a-z][a-z0-9_]*$"},
        "severity": {"$ref": "#/$defs/severity"},
        "pages": {"type": "array", "items": {"type": "integer", "minimum": 1}},
        "reason": {"type": ["string", "null"]},
        "message": {"type": "string"},
        "hint": {"type": ["string", "null"]}
      }
    },
    "ocr_summary": {
      "type": "object",
      "required": ["engine", "engine_version", "languages", "quality"],
      "properties": {
        "engine": {"type": "string"},
        "engine_version": {"type": "string"},
        "languages": {"type": "array", "items": {"type": "string"}},
        "quality": {"enum": ["fast", "balanced", "best"]}
      }
    },
    "conversion_result": {
      "type": "object",
      "required": ["id", "source", "destination", "outcome", "issues", "output", "password_source", "pages", "duration", "ocr"],
      "properties": {
        "id": {"$ref": "#/$defs/id"},
        "source": {"$ref": "#/$defs/abspath"},
        "destination": {"oneOf": [{"$ref": "#/$defs/abspath"}, {"type": "null"}]},
        "outcome": {"$ref": "#/$defs/outcome"},
        "issues": {"type": "array", "items": {"$ref": "#/$defs/issue"}},
        "output": {"oneOf": [{"$ref": "#/$defs/abspath"}, {"type": "null"}]},
        "password_source": {"type": ["string", "null"]},
        "pages": {"type": ["integer", "null"], "minimum": 0},
        "duration": {"type": "number", "minimum": 0},
        "ocr": {"oneOf": [{"$ref": "#/$defs/ocr_summary"}, {"type": "null"}]}
      }
    },
    "batch_started": {
      "properties": {
        "type": {"const": "batch_started"},
        "tool_version": {"type": "string"},
        "total": {"type": "integer", "minimum": 0},
        "jobs": {"type": "integer", "minimum": 1},
        "planned": {"type": "array", "items": {
          "type": "object",
          "required": ["id", "source", "destination"],
          "properties": {
            "id": {"$ref": "#/$defs/id"},
            "source": {"$ref": "#/$defs/abspath"},
            "destination": {"oneOf": [{"$ref": "#/$defs/abspath"}, {"type": "null"}]}
          }
        }}
      },
      "required": ["tool_version", "total", "jobs", "planned"]
    },
    "conversion_started": {
      "properties": {"type": {"const": "conversion_started"}, "id": {"$ref": "#/$defs/id"}},
      "required": ["id"]
    },
    "progress": {
      "properties": {
        "type": {"const": "progress"},
        "id": {"$ref": "#/$defs/id"},
        "stage": {"enum": ["open", "analyse", "ocr", "reflow", "write"]},
        "done": {"type": "integer", "minimum": 0},
        "of": {"type": "integer", "minimum": 0},
        "page": {"type": "integer", "minimum": 1},
        "trigger": {"enum": ["no_text_layer", "text_layer_rejected", "forced"]},
        "confidence": {"type": ["number", "null"], "minimum": 0, "maximum": 1},
        "coverage": {"type": ["number", "null"], "minimum": 0, "maximum": 1},
        "attempts": {"type": "integer", "minimum": 0},
        "fell_back": {"type": "boolean"}
      },
      "required": ["id", "stage", "done", "of"],
      "allOf": [
        {"if": {"properties": {"stage": {"enum": ["analyse", "ocr"]}}},
         "then": {"required": ["page"]}},
        {"if": {"properties": {"stage": {"const": "ocr"}}},
         "then": {"required": ["page", "trigger", "confidence", "coverage", "attempts", "fell_back"]}}
      ]
    },
    "issue_event": {
      "properties": {
        "type": {"const": "issue"},
        "id": {"oneOf": [{"$ref": "#/$defs/id"}, {"type": "null"}]},
        "issue": {"$ref": "#/$defs/issue"}
      },
      "required": ["id", "issue"]
    },
    "password_required": {
      "properties": {
        "type": {"const": "password_required"},
        "id": {"$ref": "#/$defs/id"},
        "sources_tried": {"type": "array", "items": {"type": "string"}}
      },
      "required": ["id", "sources_tried"]
    },
    "password_request": {
      "properties": {
        "type": {"const": "password_request"},
        "id": {"$ref": "#/$defs/id"},
        "request_id": {"type": "string"},
        "attempt": {"type": "integer", "minimum": 1, "maximum": 3}
      },
      "required": ["id", "request_id", "attempt"]
    },
    "conversion_finished": {
      "allOf": [{"$ref": "#/$defs/conversion_result"}],
      "properties": {"type": {"const": "conversion_finished"}}
    },
    "batch_finished": {
      "properties": {
        "type": {"const": "batch_finished"},
        "tool_version": {"type": "string"},
        "started_at": {"type": "string", "format": "date-time"},
        "totals": {
          "type": "object",
          "required": ["converted", "skipped", "failed"],
          "properties": {
            "converted": {"type": "integer", "minimum": 0},
            "skipped": {"type": "integer", "minimum": 0},
            "failed": {"type": "integer", "minimum": 0}
          }
        },
        "interrupted": {"type": "boolean"},
        "exit_code": {"enum": [0, 1, 130]},
        "conversions": {"type": "array", "items": {"$ref": "#/$defs/conversion_result"}}
      },
      "required": ["tool_version", "started_at", "totals", "interrupted", "exit_code", "conversions"]
    }
  }
}
```

## 14. Acceptance criteria

Fixture names refer to the fixtures in [testing](testing.md).

<a id="api-ac1"></a>**API-AC1** (covers [API-R2](#api-r2), [API-R18](#api-r18)): **Given** inputs `[novel.pdf, missing.pdf]` where `missing.pdf` does not exist, **when** `plan_batch` and then `run_batch` run, **then** the plan has two entries with `id` 0 and 1, and the sink receives `batch_started` (`total` = 2), then `conversion_finished` for `id` 1 with `outcome` `failed` and one issue `not_found`, before any `conversion_started`; `conversion_started` is emitted for `id` 0 only.

<a id="api-ac2"></a>**API-AC2** (covers [API-R3](#api-r3), [API-R4](#api-r4), [API-R16](#api-r16), [API-R17](#api-r17)): **Given** a single born-digital fixture and `isolation="inprocess"`, **when** `run_batch` returns, **then** the recorded events begin with `batch_started` and end with `batch_finished`, contain exactly one `conversion_started` and one `conversion_finished` for `id` 0, every event has `v` = 1, `t` never decreases, every sink call happened on the thread that called `run_batch`, and the returned `BatchReport` equals the `batch_finished` payload once the envelope fields `v`, `type` and `t` are removed.

<a id="api-ac3"></a>**API-AC3** (covers [API-R5](#api-r5)): **Given** the same born-digital fixture and the same options, **when** it is converted once with `isolation="subprocess"` and once with `isolation="inprocess"`, **then** both runs produce the same sequence of event types, the same outcome, the same issue codes and byte-identical EPUBs.

<a id="api-ac4"></a>**API-AC4** (covers [API-R6](#api-r6)): **Given** a three-file batch and a sink that calls `cancel.cancel()` on the first `progress` event of `id` 0, **when** `run_batch` returns, **then** the report has `interrupted` = `true`, `exit_code` = 130, and conversions 1 and 2 have outcome `skipped` with issue `not_attempted`.

<a id="api-ac5"></a>**API-AC5** (covers [API-R7](#api-r7), [API-R8](#api-r8)): **Given** `Secret("hunter2")`, **when** it is passed to `str`, `repr`, an f-string and `json.dumps`, **then** the first three give `***` and `json.dumps` raises `TypeError`; **and given** an encrypted fixture whose password is `hunter2` supplied by a provider with source `cli #1`, **when** the batch runs, **then** `conversion_finished.password_source` is `cli #1` and the text `hunter2` appears in no event, no report and no captured log record.

<a id="api-ac6"></a>**API-AC6** (covers [API-R9](#api-r9)): **Given** each options class constructed with no arguments, **when** a field is assigned after construction, **then** `dataclasses.FrozenInstanceError` is raised, and each class's no-argument construction succeeds (every field has a core default).

<a id="api-ac7"></a>**API-AC7** (covers [API-R10](#api-r10), [API-R12](#api-r12)): **Given** conversions whose issue sets are (a) `{page_fallback}`, (b) `{output_exists}`, (c) `{restricted}`, (d) `{not_attempted}`, (e) `{missing_password, page_fallback}`, (f) `{}`, **when** outcomes are derived, **then** they are (a) `converted`, (b) `skipped`, (c) `failed`, (d) `skipped`, (e) `failed`, (f) `converted`; **and** every `IssueCode` member's severity equals the registry table.

<a id="api-ac8"></a>**API-AC8** (covers [API-R11](#api-r11)): **Given** a conversion in which pages 7 and 3 fall back as `complex` and page 5 falls back as `multi_column`, **when** it finishes, **then** `conversion_finished.issues` contains exactly two `page_fallback` issues: `reason` `complex` with `pages` `[3, 7]` and `reason` `multi_column` with `pages` `[5]`.

<a id="api-ac9"></a>**API-AC9** (covers [API-R13](#api-r13), [API-R14](#api-r14), [API-R15](#api-r15), [API-R19](#api-r19)): **Given** a batch `[b.pdf, a.pdf]` run through the CLI with `--json --report report.json` from a relative working directory, **when** it finishes, **then** `report.json` parses to the same object as the last stdout line (`batch_finished`), `conversions[0].source` ends in `b.pdf`, every path field in the stream and report is absolute, and each `conversions[i]` has exactly the `ConversionResult` fields.

<a id="api-ac10"></a>**API-AC10** (covers [API-R20](#api-r20), [API-R28](#api-r28)): **Given** a two-file batch, **when** the CLI runs with `--json --debug`, **then** every stdout line parses as a JSON object with `v` = 1, the last line has `type` `batch_finished`, and log records appear on stderr only.

<a id="api-ac11"></a>**API-AC11** (covers [API-R21](#api-r21)): **Given** a three-page born-digital fixture, **when** it converts, **then** its `progress` events have stages in the order `open`, `analyse` ×3 (`done` 1, 2, 3, `of` 3, `page` 1, 2, 3), `reflow`, `write`, and there is no `ocr` stage event.

<a id="api-ac12"></a>**API-AC12** (covers [API-R22](#api-r22)): **Given** a two-page image-only scanned fixture and Tesseract installed, **when** it converts with OCR mode `auto`, **then** there are two `progress` events with stage `ocr`, each with `trigger` `no_text_layer`, `confidence` and `coverage` in [0, 1], `attempts` ≥ 1 and a boolean `fell_back`, and `conversion_finished.ocr.engine` is `tesseract`.

<a id="api-ac13"></a>**API-AC13** (covers [API-R23](#api-r23)): **Given** an encrypted fixture and no password sources, **when** the CLI runs with `--json --interactive` and the test answers the `password_request` with `{"type":"password","request_id":<id>,"password":"<correct>"}`, **then** the conversion's outcome is `converted` with `password_source` `prompt`; **and when** instead it sends `{"type":"cancel"}`, **then** the last event is `batch_finished` with `interrupted` = `true` and the process exits with 130.

<a id="api-ac14"></a>**API-AC14** (covers [API-R24](#api-r24), [API-R25](#api-r25), [API-R26](#api-r26)): **Given** the packaged schema `events.v1.json`, **when** every event emitted across the test suite and every `--report` file written by it is validated, **then** all validate; **and** an otherwise valid event with an extra unknown field validates, while one with `v` = 2 does not.

<a id="api-ac15"></a>**API-AC15** (covers [API-R27](#api-r27)): **Given** any batch, **when** it runs, **then** `batch_started.jobs` is 1 and every event of type `conversion_started`, `progress`, `password_required`, `password_request` and `conversion_finished` has an integer `id` that appears in `batch_started.planned`.

<a id="api-ac16"></a>**API-AC16** (covers [API-R1](#api-r1)): **Given** the installed package, **when** `pdf2epub --json` converts the novel fixture, **then** every stdout line validates against the schema shipped in the package, whose `v` is the constant `1`; **and** the `pdf2epub` package docstring and the API reference page both state that the Python API is provisional and may change in any 0.x release, while the `--json` protocol is the stable contract.

## Open points

- Page numbers in issues and `progress.page` are **1-based PDF page indices** (not printed page labels). Assumed; not fixed by a decision.
- `progress` events of stages `analyse` and `ocr` carry a `page` field; the decisions named only `done`/`of`. Added so front ends can show which page is being OCR'd.
- `ConversionResult` gained `ocr` (from the OCR decision) and `BatchReport` lists `tool_version`/`started_at` on `batch_finished`; `exit_code` in the schema is limited to 0, 1 and 130 because usage errors (2) produce no batch.
- Grouping is per **(code, reason)** pair, so `Issue` keeps a single `reason`; this reconciles "one issue per code with a page list" with per-page reasons.
- A page whose OCR crashed or timed out appears both in `ocr_failed`/`ocr_timeout` (engine diagnostic) and in exactly one `page_fallback` issue with the matching reason.
- stdin messages carry no `v` field; unknown or malformed lines are ignored. End of stdin is treated as declining pending requests.
- `Secret.reveal()` is the assumed name of the only accessor.
- `"inprocess"` vs `"subprocess"` equivalence (API-AC3) assumes deterministic EPUB output as specified in [epub](epub.md).
