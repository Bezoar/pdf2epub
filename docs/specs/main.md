# pdf2epub — main specification

**Status:** draft · **Depends on:** — · **Decisions:** [MIT-compatible PDF library stack](https://github.com/Bezoar/pdf2epub/issues/2), [Scope of password-based PDF decryption](https://github.com/Bezoar/pdf2epub/issues/3), [Front-end integration patterns for the core](https://github.com/Bezoar/pdf2epub/issues/4), [v1 scope cut and roadmap contents](https://github.com/Bezoar/pdf2epub/issues/6), [Implementation language and packaging](https://github.com/Bezoar/pdf2epub/issues/7), [Spec breakdown into main and satellite specs](https://github.com/Bezoar/pdf2epub/issues/14), [ADR 0001](../adr/0001-python-core.md)

This is the entry point to the pdf2epub specification. It owns the purpose, the legal scope, use cases, goals and non-goals, the architecture overview with the index of which spec owns what, the cross-cutting non-functional requirements, and the top-level v1 acceptance criteria (a)–(g). Everything else is in a satellite spec (see [§5](#52-which-spec-owns-what)). Vocabulary follows [`GLOSSARY.md`](../../GLOSSARY.md).

## 1. Purpose

pdf2epub converts PDF books, born-digital or scanned, into reflowable EPUB 3 books for personal reading and backup. It handles one conversion at a time or a batch. The default path is one command with no flags:

```
pdf2epub book.pdf            # writes book.epub next to it
```

The hard problem is not writing EPUB files. It is recovering structure (paragraphs, headings, chapters, reading order) from a PDF, which stores only positioned glyphs or, for a scan, only pictures of pages. Most of the specification is about doing that well and, when it can't be done for a page, falling back to a page image instead of emitting garbage.

<a id="main-r1"></a>**MAIN-R1**: pdf2epub shall convert each input PDF into a single EPUB 3 file that passes epubcheck with zero errors (detail in [epub](epub.md)).

<a id="main-r2"></a>**MAIN-R2**: pdf2epub shall run fully offline: it shall make no network access, collect no telemetry, and never send a file or any part of one off the machine.

## 2. Legal scope

<a id="legal-scope"></a>pdf2epub is a public tool published on PyPI. To keep it clearly on the right side of anti-circumvention law (US DMCA §1201, EU InfoSoc Directive Art. 6), its scope is fixed as follows. This is risk reduction, not legal advice.

<a id="main-r3"></a>**MAIN-R3**: pdf2epub shall never circumvent DRM or any access or copy control. No code, documentation or roadmap item shall attempt to bypass one.

<a id="main-r4"></a>**MAIN-R4**: The only decryption pdf2epub performs shall be opening a **password-protected PDF** (PDF Standard Security Handler) with a password the user supplies. Opening a file with a password its owner gave the user is the authorised means of access, not circumvention. Detail: [passwords](passwords.md).

<a id="main-r5"></a>**MAIN-R5**: A **DRM-protected** file (any security handler other than Standard, or a vendor wrapper such as Readium LCP or an Adobe `.acsm` token) shall be detected and refused with [`drm_protected`](api.md#code-drm_protected). No password is tried against it.

<a id="main-r6"></a>**MAIN-R6**: **Permission restrictions** shall be honoured. If a PDF forbids copying or extracting content, the conversion shall be refused with [`restricted`](api.md#code-restricted) unless the user supplies the **owner password**. There shall be no flag that overrides this.

<a id="main-r7"></a>**MAIN-R7**: pdf2epub shall never act as a password guesser. At most 25 candidate passwords are tried per file, and every candidate comes from a source the user named. Exceeding the cap is a usage error ([passwords](passwords.md)).

<a id="main-r8"></a>**MAIN-R8**: The phrase "DRM removal" shall not be used anywhere in the code, documentation, help text or issue messages, except in the negative ("does not remove DRM"). The `--help` text ([cli](cli.md)) and the README shall each state plainly: "Opens password-protected PDFs only with a password you supply. Honours permission restrictions. Does not remove DRM."

<a id="main-r9"></a>**MAIN-R9**: The README shall contain a **Legal scope** section stating MAIN-R3 to MAIN-R7 in plain language. It shall also note that the EPUB is written unencrypted, and that protecting it is the user's responsibility.

Circumvention in any form is permanently out of scope (see [§4.2](#42-non-goals)).

## 3. Users and use cases

Carried over from the archived spec, whose use-case table remains correct.

| Persona | Use case |
|---|---|
| Casual reader | Drops a novel PDF in and gets an EPUB for their e-reader. |
| Power user | Batch-converts a library, sets metadata, and reads the batch report to fix what failed. |
| Archivist | Converts scanned books with OCR and keeps the printed page numbers navigable. |

## 4. Goals and non-goals

### 4.1 Goals (v1)

- **G1 Easy:** sensible defaults; zero configuration for typical books.
- **G2 Reflowable output:** headings, paragraphs, bold and italic (born-digital only), images, and a working table of contents. Text reflows on any screen.
- **G3 Valid output:** every EPUB passes epubcheck with zero errors ([MAIN-R1](#main-r1)).
- **G4 Graceful degradation:** a page that can't be reflowed faithfully (tables, math, heavy graphics, multi-column, OCR that isn't good enough) becomes a **page-image fallback**, never garbage. Columns are never interleaved.
- **G5 Scanned books:** OCR is a core feature, using Tesseract behind an OCR-engine interface ([ocr](ocr.md)).
- **G6 Batch-friendly:** a batch never stops because one conversion fails. It ends with a batch report and meaningful exit codes ([batch](batch.md)).
- **G7 Local and private:** [MAIN-R2](#main-r2).
- **G8 Front-end ready:** the core is driven through a stable `--json` event stream, so later front ends (desktop GUI, web UI, native macOS app) need no core changes ([api](api.md)).

### 4.2 Non-goals

- **Circumventing DRM or copy controls, in any form.** This is permanently excluded, not deferred ([§2](#2-legal-scope)).
- Editing the book after conversion (Sigil and Calibre do that).
- MOBI/AZW3 output.
- Everything listed in the [roadmap](../worksheets/roadmap.md), including footnote linking (v1.1), multi-column reading order, tables and math, fixed-layout mode, parallel conversions, a config file, and all GUIs. Specs may link a roadmap item but never specify it.

## 5. Architecture

### 5.1 Overview

```
 front ends ── CLI (v1) · later: desktop GUI, web UI, macOS app (drive the CLI's --json stream)
     │
     ▼
 core API:  plan_batch(inputs) ──▶ BatchPlan ──▶ run_batch(plan, options, sink, cancel, passwords) ──▶ BatchReport
                                                    │  (one worker subprocess per conversion)
                                                    ▼
 conversion pipeline:  open & classify ─▶ analyse pages ─▶ OCR (only pages that need it) ─▶ reflow ─▶ write EPUB
                       (passwords)         (reflow)         (ocr)                           (reflow)   (epub)
```

- The **core** owns every rule: input discovery, the password trial order, outcomes, issues, exit codes. A front end only gathers inputs, builds options, and renders events. The CLI is the first front end and holds no rules of its own.
- `run_batch` is synchronous and pushes **events** to a single-threaded sink. The human report and the `--json` writer are both sinks.
- Each conversion runs in its own **worker subprocess**, so a crash or runaway conversion costs one file, never the batch.
- The `--json` wire protocol is the only **stable** contract. The Python API is documented but provisional in 0.x releases ([api](api.md)).

### 5.2 Which spec owns what

| Spec | Prefix | Owns |
|---|---|---|
| [main](main.md) | `MAIN` | Purpose, Legal scope, use cases, goals and non-goals, architecture, cross-cutting NFRs, v1 ACs (a)–(g) |
| [api](api.md) | `API` | Python API (provisional) and `--json` wire protocol (stable): event catalogue, `IssueCode` registry, outcome derivation, `ConversionResult` / `BatchReport` (= `--report` file), options shapes, versioning, JSON Schema |
| [batch](batch.md) | `BAT` | Input discovery, single conversion vs batch, output placement, atomic writes, skip/overwrite, interrupt and resume, worker isolation and timeout, exit codes |
| [passwords](passwords.md) | `PWD` | Standard-handler scope, `drm_protected` detection, the classifier, password sources and trial order, the 25-candidate cap, prompting, secret hygiene |
| [reflow](reflow.md) | `RFL` | Opening and extraction, layout, furniture, page joins, de-hyphenation, page-image fallback (including multi-column), chapters and TOC, metadata, images, cover, page sequence gaps |
| [ocr](ocr.md) | `OCR` | Which pages are OCR'd, the text-layer quality check, the `OcrEngine` protocol, the Tesseract adapter, preprocessing, coverage and confidence, the retry ladder |
| [epub](epub.md) | `EPUB` | The EPUB 3 writer, navigation, markup, deterministic packaging, validation |
| [cli](cli.md) | `CLI` | Flag surface and its mapping to core options, `--help` wording, human report rendering, `--json` / `--interactive` presentation |
| [testing](testing.md) | `TST` | Synthetic fixtures, the public-domain sample, the real-world smoke set, OCR accuracy measurement, the AC-marker gate |

How tests are written (red-green, coverage, what a tautological test is) is process, not product. It lives in [`docs/instructions/coding.md`](../instructions/coding.md).

### 5.3 Spec conventions

- **Single source of truth:** every normative fact lives in exactly one spec. Elsewhere it gets at most a one-line gist and a link.
- **Contract vs rules:** [api](api.md) owns contract types (issue codes and severities, events, report shape). The other specs own the rules for when a code fires and link to its registry entry.
- **Options** are defined by their owning spec in front-end-neutral terms, with meaning and default. [cli](cli.md) maps flags to options and never restates a default.
- **Requirement IDs** look like `PWD-R3`, and acceptance criteria like `PWD-AC3`. Each has an explicit lowercase anchor (`#pwd-r3`). IDs are never reused or renumbered; new requirements get new IDs.
- **Acceptance criteria** are Given/When/Then with concrete observable values. Every requirement is covered by at least one AC. Each test that verifies an AC carries `@pytest.mark.ac("<ID>")`, and CI fails if any AC has no marked test ([testing](testing.md)).
- **Satellite header block:** Status (draft/accepted), Depends on, Decisions (closed map tickets and ADRs, kept as history only).
- **Self-contained:** specs never defer normative detail to tickets or research branches.
- **v1 only:** future work lives only in the [roadmap](../worksheets/roadmap.md). Constraints that keep v1 ready for it (for example "parallel-ready") are v1 requirements.

## 6. Non-functional requirements

### 6.1 Platforms and runtime

<a id="main-r10"></a>**MAIN-R10**: pdf2epub shall require Python ≥ 3.12. CI shall test Python 3.12, 3.13 and 3.14.

<a id="main-r11"></a>**MAIN-R11**: macOS (Apple Silicon) and Linux (x86-64 and arm64) shall be supported and tested in CI on every PR. Windows is best-effort in v1. Full Windows support is a roadmap item.

### 6.2 Dependencies and licensing

<a id="main-r12"></a>**MAIN-R12**: pdf2epub shall be MIT-licensed (`LICENSE` at the repo root; SPDX `license = "MIT"` with `license-files` in the package metadata).

<a id="main-r13"></a>**MAIN-R13**: Every runtime dependency shall be MIT-compatible (MIT, BSD, Apache-2.0, ISC, PSF, HPND (Pillow's licence), or MPL-2.0 used unmodified). The v1 runtime dependencies are pypdfium2, pdfminer.six, pypdf, Pillow (HPND), NumPy and opencv-python-headless, plus lxml (BSD-3) and Jinja2 (BSD-3, with its MarkupSafe dependency) for the EPUB writer ([epub](epub.md)). Tesseract is an external program, not a Python dependency. AGPL libraries (PyMuPDF, ebooklib) and LGPL libraries (fpdf2) shall not be used. GPL tools (unpaper, ScanTailor) shall not be used in v1.

<a id="main-r14"></a>**MAIN-R14**: Any distribution that bundles PDFium binaries (wheels pulled in via pypdfium2, and future frozen GUI helpers) shall ship PDFium's bundled third-party notices (FreeType, libjpeg/IJG, ICU and the rest). This is attribution, not copyleft.

### 6.3 Packaging and install

<a id="main-r15"></a>**MAIN-R15**: pdf2epub shall be installable from git (`uv tool install git+https://github.com/Bezoar/pdf2epub`) and published to PyPI as `pdf2epub` with a `pdf2epub` console script. Releases follow [`docs/instructions/github.md`](../instructions/github.md): the agent prepares and checks, and only the owner uploads.

<a id="main-r16"></a>**MAIN-R16**: Tesseract shall be found on `PATH`, or at the path given by `OcrOptions.tesseract_path` ([ocr](ocr.md)). If it is missing, conversions still finish, with [`ocr_unavailable`](api.md#code-ocr_unavailable) and an install hint; it is never fatal.

<a id="main-r17"></a>**MAIN-R17**: Every install document (README, PyPI description) shall include per-platform Tesseract install steps: Homebrew on macOS, apt on Debian/Ubuntu, and how to add language packs.

### 6.4 Untrusted input

<a id="main-r18"></a>**MAIN-R18**: Every input PDF shall be treated as untrusted. pdf2epub shall never execute PDF JavaScript, follow external references or open network connections. It shall enforce image decompression and pixel limits ([`resource_limit`](api.md#code-resource_limit), rules in [reflow](reflow.md)). A per-file time limit applies ([batch](batch.md)).

<a id="main-r19"></a>**MAIN-R19**: No single input, however malformed, shall stop a batch. The worst outcome for one file is `failed` with an issue, and the batch continues ([batch](batch.md)).

### 6.5 Performance (informative)

Performance targets are informative in v1: they are not requirements and are not tested. Born-digital text pages should convert at ≥ 20 pages/s on a current laptop, and OCR'd pages are bounded by Tesseract (about 1–3 s per page per attempt). Peak memory should stay under 500 MB for a 1,000-page born-digital book. Parallel conversion is a roadmap item, but the v1 design must not foreclose it ([api](api.md)).

## 7. v1 acceptance criteria

The top-level criteria are met through the satellite ACs each one links to. The measurement criteria (e)–(g) are confirmed in a final **v1 acceptance** ticket, where the owner signs off the smoke-set results.

<a id="main-ac-a"></a>**MAIN-AC-A** (a) — Novel: **Given** the single-column novel fixture, **when** it is converted with default options, **then** the EPUB has zero epubcheck errors, a chapter TOC that matches the fixture's chapters, no running headers or page numbers in the text, and no paragraph broken at a page boundary. Elaborated in [reflow](reflow.md) and [epub](epub.md).

<a id="main-ac-b"></a>**MAIN-AC-B** (b) — Two columns: **Given** the two-column fixture, **when** it is converted, **then** no page yields interleaved column text: each page either reflows in the right reading order or becomes a page image with a [`page_fallback`](api.md#code-page_fallback) issue, reason `multi_column`. Elaborated in [reflow](reflow.md).

<a id="main-ac-c"></a>**MAIN-AC-C** (c) — Password: **Given** an encrypted fixture and its correct user password, **when** the password comes from `PDF2EPUB_PASSWORD` or from `--password`, **then** the conversion's outcome is `converted` and the password never appears in any output. Elaborated in [passwords](passwords.md).

<a id="main-ac-d"></a>**MAIN-AC-D** (d) — Mixed batch: **Given** a batch containing a corrupt PDF, an encrypted PDF with no password supplied, a DRM-protected file, a permission-restricted file and a good PDF, **when** the batch runs, **then** it finishes, converts the good file, writes no EPUB for the other four, and reports them as `corrupt_pdf`, `missing_password`, `drm_protected` and `restricted` respectively, with exit code 1. Elaborated in [batch](batch.md) and [passwords](passwords.md).

<a id="main-ac-e"></a>**MAIN-AC-E** (e) — Real readers (manual): **Given** EPUBs produced from the real-world smoke set, **when** the owner opens them, **then** they open and read correctly in Apple Books and in Calibre's viewer. This AC is **manual**: it is exempt from the marker gate and confirmed in the v1 acceptance ticket. Elaborated in [testing](testing.md).

<a id="main-ac-f"></a>**MAIN-AC-F** (f) — Test suite: **Given** the v1 code base, **when** CI runs, **then** every AC in `docs/specs/` has at least one marked test, branch coverage of `src/pdf2epub` is ≥ 75%, and no test is tautological under the definition in [`coding.md`](../instructions/coding.md). Elaborated in [testing](testing.md).

<a id="main-ac-g"></a>**MAIN-AC-G** (g) — OCR accuracy: **Given** the synthetic scanned fixtures (text rendered at 300 DPI, plus noise, 2° skew, 90° rotation and 150 DPI variants), **when** they are converted with Tesseract available, **then** character accuracy is ≥ 98% on clean variants and ≥ 95% on degraded ones (thresholds may be retuned once the fixtures exist), and pages below threshold become page images instead of emitting garbage. **Given** the same fixtures with Tesseract missing, **then** every conversion finishes with `ocr_unavailable`. Elaborated in [ocr](ocr.md) and [testing](testing.md).

Requirements MAIN-R1 to MAIN-R19 are covered by these ACs or by the satellite ACs they link to, as follows:

| Requirement | Covered by |
|---|---|
| MAIN-R1 | (a), [epub](epub.md) ACs |
| MAIN-R2 | <a id="main-ac1"></a>**MAIN-AC1**: **Given** the test suite runs with outbound network blocked (pytest-socket or equivalent), **when** every AC test runs, **then** none fails because of a blocked connection. |
| MAIN-R3–R7 | (c), (d), [passwords](passwords.md) ACs |
| MAIN-R8 | <a id="main-ac2"></a>**MAIN-AC2**: **Given** the repository, **when** CI greps the source tree, help output and README (excluding `docs/` history and this sentence's own spec), **then** the phrase "DRM removal" does not occur, and `pdf2epub --help` contains the three-sentence legal statement verbatim. |
| MAIN-R9 | MAIN-AC2 extended to the README's Legal scope section (checked in the v1 acceptance ticket) |
| MAIN-R10, R11 | <a id="main-ac4"></a>**MAIN-AC4**: **Given** the PR workflow definition, **when** it is inspected, **then** its test matrix includes Python 3.12, 3.13 and 3.14 on macOS (Apple Silicon) and on Linux x86-64 and arm64, it runs on every pull request, and the package metadata declares `requires-python = ">=3.12"`. |
| MAIN-R12–R14 | <a id="main-ac3"></a>**MAIN-AC3**: **Given** the built wheel and sdist, **when** their metadata is inspected, **then** the licence is `MIT`, `LICENSE` is included, and no runtime dependency has a licence outside MAIN-R13's list. |
| MAIN-R15, R17 | <a id="main-ac5"></a>**MAIN-AC5**: **Given** a clean macOS and a clean Linux CI runner, **when** `uv tool install git+https://github.com/Bezoar/pdf2epub` runs, **then** `pdf2epub --version` exits 0; **and given** the README, **then** it has Tesseract install steps for Homebrew, apt and language packs. |
| MAIN-R16 | (g), [ocr](ocr.md) ACs |
| MAIN-R18, R19 | (d), [reflow](reflow.md) and [batch](batch.md) ACs |

## Open points

- MAIN-AC2's grep excludes this spec and other `docs/` files, which must mention the phrase to forbid it. The exact exclusion list is fixed in ticket 0.
- The pages-per-second and memory targets in §6.5 come from the archived spec. They stay informative until a metrics corpus exists (roadmap).
