# Batches

**Status:** draft · **Depends on:** [main](main.md), [api](api.md), [passwords](passwords.md) · **Decisions:** [Batch mode semantics and end-of-batch report](https://github.com/Bezoar/pdf2epub/issues/9), [Core API shape for front ends](https://github.com/Bezoar/pdf2epub/issues/10), [Front-end integration patterns for the core](https://github.com/Bezoar/pdf2epub/issues/4)

This spec owns the rules of a batch: how inputs become planned conversions, where each EPUB goes, when a conversion is skipped, how a batch is resumed and interrupted, how conversions are isolated and timed out, and the exit code. Every run, even of one file, uses this machinery. The contract types it fires (issue codes, events, the batch report) are owned by [api](api.md); flag names and the human report are owned by [cli](cli.md); password rules by [passwords](passwords.md).

## 1. Inputs

<a id="bat-r1"></a>**BAT-R1**: A batch's inputs shall be any number of positional paths (files or folders), in the order given, followed by the paths listed in the files-from list, if any, in file order.

<a id="bat-r2"></a>**BAT-R2**: A files-from list shall hold one path per line, read from a file or from stdin (`-`). Blank lines and lines whose first non-blank character is `#` shall be ignored, and surrounding whitespace trimmed. Relative paths are relative to the current working directory. pdf2epub shall not expand glob patterns; that is left to the shell.

<a id="bat-r3"></a>**BAT-R3**: A folder input shall be scanned **one level deep** by default and through all subfolders when `DiscoveryOptions.recursive` is set. A scan shall select files whose name ends in `.pdf` in any letter case, skip hidden files and hidden folders (name starting with `.`), and not follow symbolic links to folders.

<a id="bat-r4"></a>**BAT-R4**: Every selected file shall be checked by **content**: it is a PDF only if the bytes `%PDF-` occur within its first 1024 bytes. An explicitly named file is checked whatever its extension. A path that does not exist or cannot be read shall get [`not_found`](api.md#code-not_found); a file that fails the content check shall get [`not_a_pdf`](api.md#code-not_a_pdf), except that an explicitly named DRM wrapper (a Readium LCP archive or an Adobe `.acsm` token, as defined in [PWD-R3](passwords.md#pwd-r3)) is passed on so that it is refused as [`drm_protected`](api.md#code-drm_protected). Both are decided at planning time.

<a id="bat-r5"></a>**BAT-R5**: Inputs that resolve to the same file (after resolving symbolic links) shall be converted once, at the position of their first occurrence.

<a id="bat-r6"></a>**BAT-R6**: Planned conversions shall follow input order; the files found in one folder shall follow **natural sort order** of their paths relative to that folder (case-insensitive, runs of digits compared as numbers, so `ch2.pdf` precedes `ch10.pdf`).

## 2. Single conversion and batch

<a id="bat-r7"></a>**BAT-R7**: A run shall be a **single conversion** only when it has exactly one input and that input is an explicitly named file (not a folder, not a files-from list). Any other run is a **batch**, including a folder that holds one PDF.

<a id="bat-r8"></a>**BAT-R8**: The single-conversion distinction shall affect only (a) whether the password prompt is automatic ([passwords](passwords.md)) and (b) whether the CLI prints a one-line result or the full batch report ([cli](cli.md)). Discovery, outputs, isolation, events and exit codes are identical.

## 3. Output placement and existing outputs

<a id="bat-r9"></a>**BAT-R9**: By default each EPUB shall be written next to its source PDF as `<source stem>.epub`.

<a id="bat-r10"></a>**BAT-R10**: When `DiscoveryOptions.output` is set, it shall name the EPUB file for a single conversion and the output folder for a batch. In a batch the folder is created if missing; files named explicitly go directly into it; files found in a folder input go into it under their path relative to that folder input (so with recursion the subfolder tree is mirrored). A batch whose `output` names an existing regular file is a usage error ([BAT-R25](#bat-r25)).

<a id="bat-r11"></a>**BAT-R11**: When two planned conversions map to the same destination, the first in plan order shall keep it and each later one shall be skipped with [`output_collision`](api.md#code-output_collision), decided at planning time.

<a id="bat-r12"></a>**BAT-R12**: When a destination EPUB already exists, the conversion shall be skipped with [`output_exists`](api.md#code-output_exists), decided at planning time, unless `BatchOptions.overwrite` is set, in which case it is converted and replaces the existing file on success.

<a id="bat-r13"></a>**BAT-R13**: An EPUB shall be written **atomically**: to a temporary file in the destination folder, renamed over the destination only after the whole EPUB is complete. A half-written EPUB shall never be left at the destination, and the temporary file shall be deleted when the conversion fails, times out or is cancelled.

<a id="bat-r14"></a>**BAT-R14**: A conversion that fails shall never modify or delete an existing EPUB at its destination, with or without `overwrite`.

<a id="bat-r15"></a>**BAT-R15**: When the EPUB cannot be written (destination folder not creatable or writable, disk full, rename refused), the conversion shall fail with [`write_failed`](api.md#code-write_failed); the message names the destination and the operating-system reason.

## 4. Resume and interrupt

<a id="bat-r16"></a>**BAT-R16**: pdf2epub shall keep no state file between runs. Rerunning the same batch is the resume: EPUBs finished earlier are skipped as `output_exists` and the rest are converted.

<a id="bat-r17"></a>**BAT-R17**: When the batch is cancelled (the `CancelToken`, see [api §3](api.md#3-cancellation)), the core shall stop the running conversion — with `isolation = "subprocess"` by terminating its worker (SIGTERM, then SIGKILL after a 5-second grace); with `isolation = "inprocess"` by checking the token at every stage and page boundary and stopping at the next one — then delete its temporary file, mark the cancelled conversion and every conversion not yet started as skipped with [`not_attempted`](api.md#code-not_attempted), emit their `conversion_finished` events, and finish with `batch_finished` (`interrupted` = `true`, `exit_code` = 130). Conversions already finished keep their outcomes and EPUBs.

<a id="bat-r18"></a>**BAT-R18**: The CLI shall treat the **first** SIGINT (Ctrl-C) or SIGTERM as cancellation per [BAT-R17](#bat-r17) and print the report. A **second** SIGINT shall end the process immediately with exit code 130, without a report; temporary files may then remain (they are hidden and never at a destination path).

## 5. Isolation and timeouts

<a id="bat-r19"></a>**BAT-R19**: With `BatchOptions.isolation = "subprocess"`, each conversion shall run in its **own worker subprocess**, one conversion at a time, and the parent process shall emit all events.

<a id="bat-r20"></a>**BAT-R20**: When a worker crashes, is killed by the operating system, runs out of memory or exits without a result, that conversion shall fail with [`internal_error`](api.md#code-internal_error) (message ending "please report this bug") and the batch shall continue with the next conversion. An unexpected exception inside a conversion (in either isolation mode) shall likewise become `internal_error` for that conversion only.

<a id="bat-r21"></a>**BAT-R21**: Each conversion shall have a wall-clock time limit, `BatchOptions.timeout`, measured from the start of its work. When the limit is reached, the worker shall be terminated as in [BAT-R17](#bat-r17), its temporary file deleted, and the conversion shall fail with [`timeout`](api.md#code-timeout); the batch continues. The limit is enforced only in subprocess isolation.

<a id="bat-r22"></a>**BAT-R22**: Candidate passwords shall reach a worker only over its pipe, never through its argv or environment; the worker's environment shall not contain `PDF2EPUB_PASSWORD`.

## 6. Options

<a id="bat-r23"></a>**BAT-R23**: The batch options and their defaults shall be:

| Option | Meaning | Default |
|---|---|---|
| `DiscoveryOptions.recursive` | Scan folder inputs through all subfolders ([BAT-R3](#bat-r3)). | `False` |
| `DiscoveryOptions.output` | Destination file (single conversion) or folder (batch) ([BAT-R10](#bat-r10)). | `None` (next to source) |
| `BatchOptions.timeout` | Per-conversion time limit in seconds ([BAT-R21](#bat-r21)). | `1800` (30 minutes) |
| `BatchOptions.overwrite` | Replace existing EPUBs ([BAT-R12](#bat-r12)). | `False` |
| `BatchOptions.isolation` | `"subprocess"` or `"inprocess"` ([api](api.md#api-r5)). | `"subprocess"` |
| `BatchOptions.strict` | Count warnings as failures for the exit code ([BAT-R24](#bat-r24)). | `False` |

## 7. Exit codes

Outcomes are derived from issues as defined in [api](api.md#api-r12).

<a id="bat-r24"></a>**BAT-R24**: The batch's exit code shall be:

| Code | When |
|---|---|
| `130` | The batch was interrupted ([BAT-R17](#bat-r17)). Takes precedence over all others. |
| `1` | At least one conversion failed; or `strict` is set and at least one conversion has a `warning` issue. |
| `0` | Every conversion converted or was skipped; warnings allowed unless `strict`. |

Under `strict`, EPUBs with warnings are still written. Exit codes 3 and 4 of the archived draft do not exist.

<a id="bat-r25"></a>**BAT-R25**: A **usage error** (invalid or conflicting options, an unreadable files-from list or password map, a batch `output` that is an existing regular file, the password-candidate cap exceeded ([passwords](passwords.md)), an invalid OCR engine option ([ocr](ocr.md))) shall be detected before any conversion starts and shall end the run with exit code `2`: no conversion runs, no EPUB is written, and no `batch_started` event is emitted. The CLI prints the reason on stderr.

## 8. Acceptance criteria

Fixture names refer to the fixtures in [testing](testing.md). Unless stated, runs use the Python API with `isolation="inprocess"`.

<a id="bat-ac1"></a>**BAT-AC1** (covers [BAT-R1](#bat-r1), [BAT-R2](#bat-r2)): **Given** positional inputs `[c.pdf, a.pdf]` and a files-from list on stdin containing `# comment`, a blank line, `  b.pdf  `, **when** the batch is planned, **then** the plan sources are, in order, `c.pdf`, `a.pdf`, `b.pdf` (absolute), and a literal input `*.pdf` that names no file gets `not_found`.

<a id="bat-ac2"></a>**BAT-AC2** (covers [BAT-R3](#bat-r3)): **Given** a folder holding `one.PDF`, `.hidden.pdf`, `notes.txt`, a subfolder `sub/two.pdf`, and a symbolic link `link → other-folder/` holding `three.pdf`, **when** it is planned without `recursive`, **then** the plan holds only `one.PDF`; **and with** `recursive`, **then** it holds `one.PDF` and `sub/two.pdf`, never `.hidden.pdf` or `three.pdf`.

<a id="bat-ac3"></a>**BAT-AC3** (covers [BAT-R4](#bat-r4)): **Given** an explicitly named `book.dat` that is a valid PDF and an explicitly named `fake.pdf` holding plain text, **when** the batch runs, **then** `book.dat` converts to `book.epub` and `fake.pdf` fails with `not_a_pdf`, reported in a `conversion_finished` event before any `conversion_started`.

<a id="bat-ac4"></a>**BAT-AC4** (covers [BAT-R5](#bat-r5), [BAT-R6](#bat-r6)): **Given** inputs `[dir/, dir/ch2.pdf]` where `dir` holds `ch10.pdf`, `ch2.pdf`, `Ch1.pdf`, **when** the batch is planned, **then** the plan is `Ch1.pdf`, `ch2.pdf`, `ch10.pdf` (three entries; the second mention of `ch2.pdf` is dropped).

<a id="bat-ac5"></a>**BAT-AC5** (covers [BAT-R7](#bat-r7), [BAT-R8](#bat-r8)): **Given** (a) one explicitly named PDF and (b) a folder holding exactly that PDF, **when** each runs through the CLI, **then** (a) prints a one-line result and (b) prints the batch report, and both emit the same event types in `--json` mode and exit 0.

<a id="bat-ac6"></a>**BAT-AC6** (covers [BAT-R9](#bat-r9), [BAT-R10](#bat-r10)): **Given** `books/` holding `a.pdf` and `sub/b.pdf`, **when** a recursive batch runs with no `output`, **then** it writes `books/a.epub` and `books/sub/b.epub`; **and with** `output` = `out/` (not existing), **then** it creates `out/a.epub` and `out/sub/b.epub`; **and** a single conversion of `a.pdf` with `output` = `x/My Book.epub` writes exactly that file.

<a id="bat-ac7"></a>**BAT-AC7** (covers [BAT-R11](#bat-r11)): **Given** `one/book.pdf` and `two/book.pdf` with `output` = `out/`, **when** the batch runs, **then** `out/book.epub` is converted from `one/book.pdf` and `two/book.pdf` is skipped with `output_collision` (severity `info`), and the exit code is 0.

<a id="bat-ac8"></a>**BAT-AC8** (covers [BAT-R12](#bat-r12), [BAT-R16](#bat-r16)): **Given** a batch of three PDFs where `b.epub` already exists, **when** it runs, **then** `b.pdf` is skipped with `output_exists`, the others convert, and exit code is 0; **when** it is run again, **then** all three are skipped with `output_exists`; **and with** `overwrite`, **then** all three convert and `b.epub` is replaced.

<a id="bat-ac9"></a>**BAT-AC9** (covers [BAT-R13](#bat-r13), [BAT-R14](#bat-r14)): **Given** an existing `bad.epub` with known bytes, and `bad.pdf` that fails conversion (e.g. `corrupt_pdf`), **when** the batch runs with `overwrite`, **then** `bad.epub` is byte-identical afterwards and no temporary file remains in its folder; **and given** a conversion cancelled during its `write` stage, **then** no file other than pre-existing ones remains in the destination folder.

<a id="bat-ac10"></a>**BAT-AC10** (covers [BAT-R15](#bat-r15)): **Given** a destination folder that is not writable, **when** a PDF is converted into it, **then** the conversion fails with `write_failed` naming the destination, and the exit code is 1.

<a id="bat-ac11"></a>**BAT-AC11** (covers [BAT-R17](#bat-r17)): **Given** a three-file batch in subprocess isolation, **when** the cancel token is set while conversion 1 is running, **then** conversion 0 keeps outcome `converted` and its EPUB, conversions 1 and 2 are `skipped` with `not_attempted` and have no EPUB or temporary file, the last event is `batch_finished` with `interrupted` = `true`, and `exit_code` = 130.

<a id="bat-ac12"></a>**BAT-AC12** (covers [BAT-R18](#bat-r18)): **Given** the CLI converting a slow multi-file batch, **when** it receives one SIGINT, **then** it prints the batch report on stderr and exits with 130; **when** it receives a second SIGINT before finishing, **then** it exits with 130 immediately without printing a report.

<a id="bat-ac13"></a>**BAT-AC13** (covers [BAT-R19](#bat-r19), [BAT-R20](#bat-r20)): **Given** a batch `[crash.pdf, good.pdf]` in subprocess isolation where a test hook makes the worker for `crash.pdf` abort the process, **when** the batch runs, **then** `crash.pdf` fails with `internal_error` whose message ends "please report this bug", `good.pdf` converts, and the exit code is 1; **and given** a test hook that raises an unexpected exception during conversion in `inprocess` mode, **then** that conversion fails with `internal_error` and the batch continues.

<a id="bat-ac14"></a>**BAT-AC14** (covers [BAT-R21](#bat-r21)): **Given** `timeout` = 2 seconds and a test hook that makes the worker sleep for 60 seconds, **when** the batch runs, **then** the conversion fails with `timeout` in under 15 seconds, no temporary file remains, and the next conversion in the batch runs.

<a id="bat-ac15"></a>**BAT-AC15** (covers [BAT-R22](#bat-r22)): **Given** an encrypted fixture, `PDF2EPUB_PASSWORD` set to its password, and a test hook that records the worker's argv and environment, **when** the batch runs in subprocess isolation, **then** the file converts and the password appears in neither the recorded argv nor the recorded environment.

<a id="bat-ac16"></a>**BAT-AC16** (covers [BAT-R23](#bat-r23)): **Given** `DiscoveryOptions()` and `BatchOptions()` with no arguments, **when** their fields are read, **then** `recursive` is `False`, `output` is `None`, `timeout` is 1800, `overwrite` is `False`, `isolation` is `"subprocess"` and `strict` is `False`.

<a id="bat-ac17"></a>**BAT-AC17** (covers [BAT-R24](#bat-r24)): **Given** batches whose results are (a) all converted with one `page_fallback` warning, (b) one `missing_password` failure among conversions, (c) only `output_exists` skips, **when** each finishes, **then** the exit codes are (a) 0, (b) 1, (c) 0; **and** (a) run with `strict` exits 1 and still writes its EPUB.

<a id="bat-ac18"></a>**BAT-AC18** (covers [BAT-R25](#bat-r25)): **Given** the CLI with (a) an unknown flag, (b) `--files-from` naming a missing file, (c) two inputs and `-o` naming an existing regular file, **when** each runs, **then** each exits with 2, prints the reason on stderr, writes no EPUB, and in `--json` mode emits no `batch_started` event.

## Open points

- Positional inputs come before files-from entries when both are given; the decision said only "as given".
- The PDF content check looks for `%PDF-` within the first 1024 bytes (the tolerance common PDF readers use).
- Folder inputs mirror their relative tree under `output` even without `--recursive` (one level: no subfolders exist to mirror).
- The conversion running when the batch is cancelled is reported `not_attempted` (outcome `skipped`), like the unstarted ones; a rerun converts it.
- Grace period between SIGTERM and SIGKILL is 5 seconds.
- `timeout` is not enforced in `inprocess` isolation (there is no worker to kill).
- A second SIGINT may leave a hidden temporary file in a destination folder; it is never at a destination path.
- A usage error emits no events at all, so `exit_code` 2 never appears in a `batch_finished` event.
