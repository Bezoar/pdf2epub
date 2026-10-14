# Command-line interface

**Status:** draft · **Depends on:** [main](main.md), [api](api.md), [batch](batch.md), [passwords](passwords.md), [reflow](reflow.md), [ocr](ocr.md) · **Decisions:** [Batch mode semantics and end-of-batch report](https://github.com/Bezoar/pdf2epub/issues/9), [Password and decryption UX](https://github.com/Bezoar/pdf2epub/issues/8), [Core API shape for front ends](https://github.com/Bezoar/pdf2epub/issues/10), [OCR engine interface design](https://github.com/Bezoar/pdf2epub/issues/13), [Front-end integration patterns for the core](https://github.com/Bezoar/pdf2epub/issues/4), [ADR 0001](../adr/0001-python-core.md)

The command line is the first **front end**. This spec owns:

- the flag surface: names, syntax, environment variables, repeatability, and which core option each flag sets;
- the `--help` and warning wording;
- the human report rendered on stderr;
- how `--json` and `--interactive` are presented.

It does **not** define what an option means or its default. The owning spec does that: [batch](batch.md), [passwords](passwords.md), [reflow](reflow.md) or [ocr](ocr.md). It doesn't define the event and report shapes either; those belong to [api](api.md). The CLI holds no batch, password or conversion rules of its own. It parses argv, builds the core inputs, calls `plan_batch` and `run_batch`, and renders events through a sink.

## 1. Invocation and streams

<a id="cli-r1"></a>**CLI-R1**: The command shall be `pdf2epub [options] INPUT...`, also runnable as `python -m pdf2epub`.

<a id="cli-r2"></a>**CLI-R2**: The streams shall be used as follows:

- **stdout** stays empty unless `--json` is given. With `--json`, stdout carries only events, one JSON object per line (JSON Lines), and each line is flushed as it is written.
- **stderr** carries progress, the human report, warnings and logging.

<a id="cli-r3"></a>**CLI-R3**: The process exit code shall be `BatchReport.exit_code`, as defined in [batch](batch.md). A usage error exits with code 2 before any conversion starts. That covers unknown flags, bad values, conflicting flags, and the usage errors the core raises at plan time.

## 2. Flags

**"Sets"** names the core option the flag sets. The meaning and default of each option are defined only in the linked spec. A flag left out leaves the option at its core default. "Rep." means the flag can be repeated.

### 2.1 Inputs and output

| Flag | Syntax | Rep. | Env | Sets |
|---|---|---|---|---|
| `INPUT` (positional) | file or folder path | yes | — | `plan_batch` inputs ([batch](batch.md)) |
| `-r`, `--recursive` | switch | — | — | `DiscoveryOptions.recursive` ([batch](batch.md)) |
| `--files-from` | `FILE` or `-` (stdin) | no | — | `plan_batch` inputs, read from the list file ([batch](batch.md)) |
| `-o`, `--output` | `PATH` | no | — | `DiscoveryOptions.output` ([batch](batch.md)) |
| `--overwrite` | switch | — | — | `BatchOptions.overwrite` ([batch](batch.md)) |
| `--timeout` | `SECONDS` (positive integer) | no | — | `BatchOptions.timeout` ([batch](batch.md)) |
| `--strict` | switch | — | — | `BatchOptions.strict` ([batch](batch.md)) |

### 2.2 Reporting and machine output

| Flag | Syntax | Rep. | Env | Sets |
|---|---|---|---|---|
| `--report` | `FILE` | no | — | CLI only: writes the `batch_finished` record ([api](api.md)) to `FILE` |
| `--json` | switch | — | — | CLI only: JSON Lines events on stdout ([§5](#5-json-and-interactive-modes)) |
| `--interactive` | switch, needs `--json` | — | — | CLI only: stdin requests ([§5](#5-json-and-interactive-modes)) |
| `-v`, `--verbose` | switch | — | — | CLI only: lists successes; logging at INFO |
| `--debug` | switch | — | — | CLI only: logging at DEBUG |
| `-q`, `--quiet` | switch | — | — | CLI only: failures and totals only |

### 2.3 Content and metadata

| Flag | Syntax | Rep. | Env | Sets |
|---|---|---|---|---|
| `--mode` | `{auto,reflow}` | no | — | `ConversionOptions.mode` ([reflow](reflow.md)) |
| `--title` | `TEXT` | no | — | `ConversionOptions.title` ([reflow](reflow.md)) |
| `--author` | `TEXT` | yes | — | `ConversionOptions.authors`, in the order given ([reflow](reflow.md)) |
| `--language` | BCP 47 tag, e.g. `en`, `de` | no | — | `ConversionOptions.language` ([reflow](reflow.md)) |
| `--cover` | `PATH` or `none` | no | — | `ConversionOptions.cover` ([reflow](reflow.md)) |

### 2.4 Passwords

| Flag | Syntax | Rep. | Env | Sets |
|---|---|---|---|---|
| `--password` | `VALUE` | yes | — | `PasswordSources.values`, in order ([passwords](passwords.md#pwd-r18)) |
| — | — | — | `PDF2EPUB_PASSWORD` | `PasswordSources.env_value` ([passwords](passwords.md#pwd-r18)) |
| `--password-file` | `FILE` | no | — | `PasswordSources.password_file` ([passwords](passwords.md#pwd-r15)) |
| `--password-map` | `FILE` (TOML) | no | — | `PasswordSources.map_file` ([passwords](passwords.md#pwd-r14)) |
| `--ask-password` | switch | — | — | `PasswordSources.prompt` set for a batch ([passwords](passwords.md#pwd-r19)) |

### 2.5 OCR

| Flag | Syntax | Rep. | Env | Sets |
|---|---|---|---|---|
| `--ocr` | `{auto,always,never}` | no | — | `OcrOptions.mode` ([ocr](ocr.md)) |
| `--ocr-lang` | Tesseract syntax, e.g. `eng`, `fra+eng` | no | — | `OcrOptions.languages` ([ocr](ocr.md)) |
| `--ocr-quality` | `{fast,balanced,best}` | no | — | `OcrOptions.quality` ([ocr](ocr.md)) |
| `--ocr-page-timeout` | `SECONDS` (positive integer) | no | — | `OcrOptions.page_timeout` ([ocr](ocr.md)) |
| `--ocr-min-confidence` | number from 0 to 1 | no | — | `OcrOptions.min_confidence` ([ocr](ocr.md)) |
| `--ocr-engine-opt` | `tesseract.KEY=VALUE` | yes | — | `OcrOptions.engine_options` (`KEY → VALUE`; the engine prefix is required) ([ocr](ocr.md)) |
| `--tessdata-dir` | `PATH` | no | — | `OcrOptions.tessdata_dir` ([ocr](ocr.md)) |
| `--tesseract` | `PATH` | no | `PDF2EPUB_TESSERACT` | `OcrOptions.tesseract_path` ([ocr](ocr.md)) |

### 2.6 General

| Flag | Effect |
|---|---|
| `--version` | Prints `pdf2epub <version>` to stdout and exits with code 0. |
| `-h`, `--help` | Prints help to stdout and exits with code 0 ([§4](#4-help-and-warnings)). |

<a id="cli-r4"></a>**CLI-R4**: Each flag shall set exactly the option in the tables above, and nothing else. The CLI shall not restate or override any core default: an option the user didn't give is left out, so the core default applies.

<a id="cli-r5"></a>**CLI-R5**: When both `--tesseract` and `PDF2EPUB_TESSERACT` are given, the flag wins. When neither is given, `OcrOptions.tesseract_path` is left unset, and the core searches `PATH` ([ocr](ocr.md)).

<a id="cli-r6"></a>**CLI-R6**: The CLI shall build the password provider as a `SourcePasswordProvider` ([passwords](passwords.md#pwd-r18)) from the raw sources. It never orders, filters or counts candidates itself. It shall set `PasswordSources.prompt` as follows:

- to a no-echo terminal prompt, when the run is a single conversion ([batch](batch.md)), stdin and stderr are terminals, and `--json` isn't given;
- to a no-echo terminal prompt, when `--ask-password` is given, stdin and stderr are terminals, and `--json` isn't given;
- to the stdin request function in [§5](#5-json-and-interactive-modes), when `--json --interactive` is given;
- otherwise, to none.

<a id="cli-r7"></a>**CLI-R7**: These combinations shall be usage errors (exit 2):

- `--interactive` without `--json`;
- `--ask-password` with `--json`;
- `--ask-password` when stdin isn't a terminal;
- `-q` with `-v` or `--debug`;
- `--ocr-engine-opt` without a `tesseract.` prefix or `=`;
- `--ocr-min-confidence` outside 0 to 1;
- a non-positive `--timeout` or `--ocr-page-timeout`;
- no inputs at all (no `INPUT` and no `--files-from`).

## 3. Logging

<a id="cli-r8"></a>**CLI-R8**: Free-text diagnostics shall go through Python `logging` to stderr only. The level is WARNING by default, INFO with `-v` and DEBUG with `--debug`. Log lines are never events and never appear on stdout ([api](api.md)).

## 4. Help and warnings

<a id="cli-r9"></a>**CLI-R9**: The `--help` description shall contain this sentence verbatim:

> Opens password-protected PDFs only with a password you supply. Honours permission restrictions. Does not remove DRM.

The epilog shall link to the README's legal section and its Tesseract install steps ([main](main.md)).

<a id="cli-r10"></a>**CLI-R10**: When at least one `--password` is given, the CLI shall print one warning line to stderr before planning. It is printed even under `-q` and `--json`:

> warning: --password values are visible to other processes on this machine; prefer --password-map, --password-file or PDF2EPUB_PASSWORD.

## 5. JSON and interactive modes

<a id="cli-r11"></a>**CLI-R11**: With `--json`, the CLI shall write every event the core emits to stdout as one JSON object per line, in emission order. The last line is `batch_finished` ([api](api.md)). The human report isn't printed. Warnings ([CLI-R10](#cli-r10), [PWD-R17](passwords.md#pwd-r17)) and logging still go to stderr.

<a id="cli-r12"></a>**CLI-R12**: Without `--interactive`, a `--json` run never prompts. Conversions that need a password produce `password_required` and are reported ([PWD-R22](passwords.md#pwd-r22)).

<a id="cli-r13"></a>**CLI-R13**: With `--json --interactive`, each prompt shall be written as a `password_request` event. The CLI then reads JSON Lines from stdin until the matching `{"type":"password","request_id":…,"password":…}` arrives. A `"password": null` answer means "skip". At any point, `{"type":"cancel"}` on stdin cancels the batch, as SIGINT does ([§7](#7-interrupts)). Lines that aren't valid JSON, or have an unknown `type` or a non-matching `request_id`, are ignored and logged at DEBUG. End of input on stdin while waiting counts as "skip".

## 6. Human report

<a id="cli-r14"></a>**CLI-R14**: When stderr is a terminal, and neither `--json` nor `-q` is given, the CLI shall show progress on one redrawn line, for example `[3/17] book.pdf · ocr 45/312`. It redraws at most about 10 times a second. When stderr isn't a terminal, there are no redraws.

<a id="cli-r15"></a>**CLI-R15**: For a **batch** ([batch](batch.md)), the report printed to stderr at the end shall contain these sections, in this order:

1. **Totals:** `Converted: N  Skipped: N  Failed: N`, plus `(interrupted)` when the batch was cancelled.
2. **Failures:** for each failed conversion in input order, a line `✗ <source>`. It is followed by one indented line per issue: `<code> [<severity>]: <message>`, then ` (pages …)` when there are pages, then ` — <hint>` when there is a hint.
3. **Warnings, condensed:** one line per converted conversion that has warnings: `! <source>: <code>(<reason>) pages …; …`.
4. **Successes:** shown as a count only. With `-v`, each converted conversion is also listed as `✓ <source> → <output>`, and each skipped one as `- <source>: <code>`.

With `-q`, only sections 1 and 2 are printed.

<a id="cli-r16"></a>**CLI-R16**: For a **single conversion** ([batch](batch.md)), the report shall be one result line, followed by indented issue lines in the format of [CLI-R15](#cli-r15):

- `✓ <source> → <output> (<pages> pages, <duration>s)` when converted;
- `- <source>: skipped (<code>)` when skipped;
- `✗ <source>: failed` when failed.

<a id="cli-r17"></a>**CLI-R17**: Page lists shall be shown as ascending ranges, for example `pages 3, 7–9, 12`.

<a id="cli-r18"></a>**CLI-R18**: `--report FILE` shall write the `batch_finished` record as one JSON document. It is written whenever the batch ends normally or is interrupted, and in either human or `--json` mode. A report file that can't be written is logged as an error, and the exit code still follows [batch](batch.md).

## 7. Interrupts

<a id="cli-r19"></a>**CLI-R19**: The first SIGINT or SIGTERM shall set the batch's `CancelToken`. The interrupt then follows [batch](batch.md): the report is printed or emitted, and the exit code is 130. A second SIGINT exits at once with code 130.

## 8. Acceptance criteria

<a id="cli-ac1"></a>**CLI-AC1** (covers [CLI-R1](#cli-r1), [CLI-R2](#cli-r2), [CLI-R3](#cli-r3)):

- **Given** the public-domain sample PDF;
- **when** `pdf2epub sample.pdf` runs as a subprocess;
- **then** stdout is empty, stderr holds the single-conversion result line, the exit code is 0 and `sample.epub` exists.

`python -m pdf2epub sample.pdf --overwrite` gives the same result.

<a id="cli-ac2"></a>**CLI-AC2** (covers [CLI-R2](#cli-r2), [CLI-R11](#cli-r11)):

- **Given** two sample PDFs;
- **when** `pdf2epub --json a.pdf b.pdf` runs;
- **then**:
  - every stdout line parses as JSON and validates against the event schema ([api](api.md));
  - the first line is `batch_started` and the last is `batch_finished`;
  - stderr contains no report section headers.

<a id="cli-ac3"></a>**CLI-AC3** (covers [CLI-R4](#cli-r4)):

- **Given** a test that captures the options passed to `plan_batch` and `run_batch`;
- **when** the CLI runs with no optional flags;
- **then** every options object equals its core default instance.

With `-r -o out --overwrite --timeout 60 --strict --mode reflow --title T --author A --author B --language de --cover none --ocr always --ocr-lang fra+eng --ocr-quality best --ocr-page-timeout 90 --ocr-min-confidence 0.8 --ocr-engine-opt tesseract.preserve_interword_spaces=1 --tessdata-dir td`, each field in the [§2](#2-flags) tables holds the given value: `authors == ["A","B"]` and `engine_options == {"preserve_interword_spaces": "1"}`.

<a id="cli-ac4"></a>**CLI-AC4** (covers [CLI-R5](#cli-r5)):

- **Given** `PDF2EPUB_TESSERACT=/env/tess`;
- **when** the CLI runs with `--tesseract /flag/tess`, then without it, then with the variable unset;
- **then** `OcrOptions.tesseract_path` is `/flag/tess`, then `/env/tess`, then unset.

<a id="cli-ac5"></a>**CLI-AC5** (covers [CLI-R6](#cli-r6)):

- **Given** `--password a --password b`, `PDF2EPUB_PASSWORD=e`, `--password-file f` and `--password-map m`;
- **when** the CLI builds the provider;
- **then** it is a `SourcePasswordProvider` whose `PasswordSources` hold `values == [a, b]`, `env_value == e`, `password_file == f` and `map_file == m`, all as `Secret`s or paths.

`prompt` is set only in the cases listed in [CLI-R6](#cli-r6), checked with stdin/stderr terminal states simulated.

<a id="cli-ac6"></a>**CLI-AC6** (covers [CLI-R3](#cli-r3), [CLI-R7](#cli-r7)):

- **Given** each combination listed in [CLI-R7](#cli-r7) (one run per combination), with a valid input;
- **when** the CLI runs;
- **then** it exits with code 2, prints a usage message to stderr, emits nothing on stdout and creates no EPUB.

<a id="cli-ac7"></a>**CLI-AC7** (covers [CLI-R8](#cli-r8)):

- **Given** a successful conversion;
- **when** it runs with `--json --debug`;
- **then** stderr contains DEBUG log lines and stdout contains only schema-valid events.

Without `-v` or `--debug`, stderr contains no INFO or DEBUG lines.

<a id="cli-ac8"></a>**CLI-AC8** (covers [CLI-R9](#cli-r9)):

- **When** `pdf2epub --help` runs;
- **then** the exit code is 0 and stdout contains the exact sentence in [CLI-R9](#cli-r9).

<a id="cli-ac9"></a>**CLI-AC9** (covers [CLI-R10](#cli-r10)):

- **Given** the AES-256 user-password fixture;
- **when** the CLI runs with `--password <correct> -q`;
- **then** stderr contains the [CLI-R10](#cli-r10) warning exactly once, and the conversion succeeds.

Without `--password`, the warning is absent.

<a id="cli-ac10"></a>**CLI-AC10** (covers [CLI-R12](#cli-r12)):

- **Given** the AES-256 user-password fixture, stdin as a pseudo-terminal, and no passwords;
- **when** `pdf2epub --json enc.pdf` runs;
- **then** nothing is read from stdin, a `password_required` event is emitted, the conversion fails with `missing_password`, and the exit code is 1.

<a id="cli-ac11"></a>**CLI-AC11** (covers [CLI-R13](#cli-r13)):

- **Given** the AES-256 user-password fixture;
- **when** `pdf2epub --json --interactive enc.pdf` runs, and the test answers the `password_request` on stdin, first with a line `not json`, then `{"type":"password","request_id":"<other>","password":"x"}`, then the matching request with the correct password;
- **then** the conversion is `converted` with `password_source == "prompt"`.

In a second run, answering `{"type":"cancel"}` ends with `interrupted: true` and exit code 130.

<a id="cli-ac12"></a>**CLI-AC12** (covers [CLI-R13](#cli-r13)):

- **Given** the same setup as CLI-AC11;
- **when** stdin is closed instead of answered;
- **then** the conversion fails with `missing_password`, and the exit code is 1.

<a id="cli-ac13"></a>**CLI-AC13** (covers [CLI-R14](#cli-r14)):

- **Given** a multi-page sample;
- **when** it runs with stderr as a pipe;
- **then** stderr contains no carriage-return redraws.

With stderr as a pseudo-terminal, progress redraws appear and are spaced at least about 100 ms apart.

<a id="cli-ac14"></a>**CLI-AC14** (covers [CLI-R15](#cli-r15), [CLI-R17](#cli-r17)):

- **Given** a batch of one converted PDF with a `page_fallback (complex)` warning on pages 3, 7, 8 and 9, one existing output, and one corrupt file;
- **when** it runs;
- **then** stderr shows, in this order:
  1. `Converted: 1  Skipped: 1  Failed: 1`;
  2. `✗ <corrupt path>` with a `corrupt_pdf [error]` line;
  3. a warnings line containing `page_fallback(complex) pages 3, 7–9`;
  4. no `✓` line.

With `-v`, a `✓` line and a `- <path>: output_exists` line also appear. With `-q`, only the totals and failure lines appear.

<a id="cli-ac15"></a>**CLI-AC15** (covers [CLI-R16](#cli-r16)):

- **Given** the public-domain sample;
- **when** `pdf2epub sample.pdf` runs;
- **then** stderr's report is a single line matching `✓ .*sample.pdf → .*sample.epub \(\d+ pages, [\d.]+s\)`.

<a id="cli-ac16"></a>**CLI-AC16** (covers [CLI-R18](#cli-r18)):

- **Given** a batch of two PDFs;
- **when** it runs with `--report r.json`, once in human mode and once with `--json`;
- **then** `r.json` is one JSON document, and it equals the `batch_finished` event emitted in the `--json` run, ignoring timing fields.

<a id="cli-ac17"></a>**CLI-AC17** (covers [CLI-R19](#cli-r19)):

- **Given** a batch of three PDFs whose first conversion is slow (test hook);
- **when** SIGINT is sent during the first conversion;
- **then**:
  - the exit code is 130;
  - the report lists the unstarted conversions as `not_attempted`;
  - `--report` shows `interrupted: true`;
  - no temp file remains.

## Open points

- **Report layout ([CLI-R15](#cli-r15), [CLI-R16](#cli-r16)):** I chose the exact human report layout (symbols `✓ ✗ ! -`, section order, line formats). The decisions fixed only the contents and their order.
- **`--ask-password` without a terminal ([CLI-R7](#cli-r7)):** I assumed this is a usage error rather than being silently ignored.
- **Malformed stdin ([CLI-R13](#cli-r13)):** I assumed malformed or unmatched stdin lines in `--interactive` are ignored and logged at DEBUG, and that end of input on stdin counts as "skip".
- **Progress when not a terminal ([CLI-R14](#cli-r14)):** I assumed no progress output at all when stderr isn't a terminal; only the report is printed.
- **`--report` failure ([CLI-R18](#cli-r18)):** I assumed a `--report` write failure doesn't change the exit code. The decisions didn't say.
- **Help and version on stdout ([§2.6](#26-general)):** `--help` and `--version` print to stdout, following the argparse convention. That is an exception to "stdout empty unless `--json`".
- **Help epilog ([CLI-R9](#cli-r9)):** I assumed the README links. Its content is owned by [main](main.md).
