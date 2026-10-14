# pdf2epub roadmap

**Status:** draft · **Decisions:** [v1 scope cut and roadmap contents](https://github.com/Bezoar/pdf2epub/issues/6), [Implementation language and packaging](https://github.com/Bezoar/pdf2epub/issues/7), [Core API shape for front ends](https://github.com/Bezoar/pdf2epub/issues/10), [OCR engine interface design](https://github.com/Bezoar/pdf2epub/issues/13), [Text-layer quality check](https://github.com/Bezoar/pdf2epub/issues/15)

This worksheet holds everything deliberately left out of v1. It is **not** a spec. Each item is described fully enough for a future session to pick it up faithfully: motivation, behaviour, interfaces touched, an AC sketch, and dependencies. When an item is scheduled, its content moves into the owning spec(s) as new requirement IDs, and the item here is reduced to a link.

**Permanently excluded, not deferred:** circumventing DRM or copy controls in any form ([Legal scope](../specs/main.md#legal-scope)). No roadmap item may touch it.

Order: [v1.1](#v11--footnote-detection-and-linking) first, then [content and layout](#content-and-layout), [OCR](#ocr), [core and CLI](#core-and-cli), [quality and tooling](#quality-and-tooling), [platforms and distribution](#platforms-and-distribution) and [integrations](#integrations), then the [GUIs](#gui-modes) in priority order. Within a section, order is a rough priority, not a commitment.

---

## v1.1 — Footnote detection and linking

- **Motivation:** v1 leaves footnotes as ordinary small paragraphs at the bottom of a page (or end of a chapter). This breaks the reading flow, and it is the most visible gap in non-fiction. The owner ranks it first.
- **Behaviour:**
  - Detect note bodies (small font, bottom of page or end of chapter, starting with a marker) and the matching reference markers in the body text (superscript digits or symbols, or bracketed numbers).
  - Link each marker to an `<aside epub:type="footnote">` with a back-link, so readers that support pop-up notes show them in place.
  - Notes continued across a page break are joined.
  - Works for born-digital text. For OCR'd text, superscripts are inferred from glyph height and baseline offset.
  - An unmatched marker or note is left as plain text with an info issue `footnote_unmatched`, never dropped.
- **Interfaces touched:** reflow (block classification, document model gains `NoteRef` and `Footnote`), epub (aside markup, landmarks), api (new issue code, additive), ocr (word baseline and height already in `OcrPageResult`).
- **AC sketch:**
  - Given a fixture with 10 numbered footnotes across 3 chapters, when converted, then each marker is a link to its aside, each aside links back, and no note text remains in the body flow.
  - Given a note continued onto the next page, then it is one aside.
  - Given OCR'd pages with footnotes, then at least 90% of markers are linked.
- **Dependencies:** v1 furniture removal and page joins. The footnote fixture is a new synthetic generator.

## Content and layout

### Multi-column reading-order reconstruction
- **Motivation:** v1 sends every multi-column page to page-image fallback (never interleaving columns). That is safe but loses reflow for papers, magazines and two-column books.
- **Behaviour:**
  - Detect column layout per page (x-projection gaps, block alignment).
  - Order blocks column-major, top to bottom, with full-width blocks (titles, figures spanning columns) placed by vertical position.
  - Applies to born-digital and OCR'd pages; OCR uses Tesseract block output, re-segmented per column.
  - Pages where ordering confidence is low still fall back with `multi_column`.
- **Interfaces touched:** reflow (layout), ocr (layout hint per column region), api (no change; existing fallback reason).
- **AC sketch:** Given the two-column fixture, then every page reflows with text in reading order (sequence matches ground truth ≥ 99%), and no interleaving occurs on any smoke-set two-column file.
- **Dependencies:** none beyond v1.

### Bold and italic in OCR'd text
- **Motivation:** the owner wants formatting kept where possible. v1 drops emphasis on OCR'd pages.
- **Behaviour:** classify each word as regular, bold or italic from stroke width and slant measured on the binarised word image. Emit inline marks only above a confidence threshold, to avoid false emphasis.
- **Interfaces touched:** ocr (`OcrPageResult` words gain optional style flags; capability flag), reflow (inline marks for OCR'd text).
- **AC sketch:** Given scanned fixtures with known emphasis, then precision ≥ 95% and recall ≥ 70% for italic and bold words.
- **Dependencies:** none.

### Tables and math
- **Motivation:** v1 sends whole pages with tables or math to page-image fallback, which also hides the surrounding prose.
- **Behaviour:**
  - **Phase 1:** detect table and formula regions and embed only the region as a cropped image (with alt text), reflowing the rest of the page.
  - **Phase 2:** tables as HTML `<table>` (from ruling lines and cell alignment); math as MathML where the source glyphs allow (born-digital only).
- **Interfaces touched:** reflow (region classification, new block types), epub (table and MathML markup, `mathml` manifest property), api (new `page_fallback` reason or new region issue, additive).
- **AC sketch:** Given a page with one table and two paragraphs, then the paragraphs reflow and the table is a cropped image (phase 1) or a `<table>` with the correct cell count (phase 2). epubcheck stays clean.
- **Dependencies:** multi-column ordering helps but isn't required.

### EPUB 3 fixed-layout mode (`--mode fixed`)
- **Motivation:** comics, picture books and design-heavy books are better as fixed pages than as reflow.
- **Behaviour:** `rendition:layout=pre-paginated`; one spine item per page: the rendered page image with an invisible text layer, positioned from text or OCR boxes. Viewport set from the page size.
- **Interfaces touched:** reflow (`ConversionOptions.mode` gains `fixed`), epub (fixed-layout package), cli (`--mode` choice).
- **AC sketch:** Given any fixture with `--mode fixed`, then the EPUB has one page per PDF page, passes epubcheck, and its text is searchable.
- **Dependencies:** none.

### Metadata heuristics
- **Motivation:** v1 metadata comes from overrides, XMP and Info dictionary, or the filename. Many PDFs have none of these.
- **Behaviour:**
  - Title-page heuristics: the largest text on the first pages → title; "by X" → author.
  - ISBN scanning on the first and last ~10 pages, validated by checksum, used as `dc:identifier`.
  - Language auto-detection from body text when no language is given (replacing v1's `en` default with `language_defaulted`).
- **Interfaces touched:** reflow (metadata precedence gains steps), epub (`dc:identifier` from ISBN), api (`language_defaulted` fires less often).
- **AC sketch:** Given fixtures with title pages and ISBNs, then title, author and ISBN are detected; given a German text with no language set, then `dc:language` is `de`.
- **Dependencies:** none.

### Automatic OCR script and language detection
- **Motivation:** v1 OCR language comes from options, metadata or `eng`. Mixed or unknown languages need manual flags.
- **Behaviour:** use Tesseract OSD script detection on sample pages, then choose installed language packs for that script. Never install packs automatically.
- **Interfaces touched:** ocr (language precedence gains a detection step; uses the existing OSD capability).
- **AC sketch:** Given a Cyrillic scan with no language set and `rus` installed, then OCR runs with `rus` and accuracy meets the clean threshold.
- **Dependencies:** none.

### Removing decorative repeated images
- **Motivation:** logos and ornaments repeated on every page clutter the reflowed text.
- **Behaviour:** detect images repeated at the same position on many pages (as furniture removal does for text) and drop them. Keep the first occurrence if it is on a title page.
- **Interfaces touched:** reflow (furniture detection for images).
- **AC sketch:** Given a fixture with a header logo on every page, then the EPUB contains the logo at most once.
- **Dependencies:** none.

### OCR of text inside figures
- **Motivation:** v1 leaves images on otherwise typeset pages as images, so text inside diagrams isn't searchable.
- **Behaviour:** OCR figure regions and attach the text as alt text or hidden searchable text. Never replace the image.
- **Interfaces touched:** ocr (region requests), epub (alt text).
- **AC sketch:** Given a typeset page with a labelled diagram, then the diagram's labels are searchable in the EPUB.
- **Dependencies:** OCR region support (see [OCR engine extensions](#ocr-engine-extensions)).

### Wordlists for more languages
- **Motivation:** v1 ships only an English wordlist. Other languages get soft-hyphen-only de-hyphenation (so `Wör-ter` split at a line end keeps its hyphen) and a weaker, letters-only word-plausibility signal in the text-layer quality check.
- **Behaviour:**
  - **Triage first (owner decision):** pick the first languages to support, ranked on reader demand, how much hard-hyphenation they use, and whether an MIT-compatible wordlist exists (many Hunspell dictionaries are GPL, LGPL or MPL, which [coding.md §9](../instructions/coding.md#9-dependencies) requires escalating). Contributor research: [Wordlist licences and language triage for more languages (#53)](https://github.com/Bezoar/pdf2epub/issues/53).
  - Ship one wordlist per chosen language, selected by the book's language (the same language that drives OCR), for both de-hyphenation and word plausibility.
  - **Contributed lists (shipped):** one file per language, `wordlists/<bcp47>.txt` (UTF-8, NFC, one word per line, sorted, no duplicates) plus `wordlists/<bcp47>.source.toml` (source URL, version, SPDX licence ID, generation script, SHA-256). The English list in v1 already uses this layout.
  - **CI gatekeeping for contributions:** reject licences outside an MIT-compatible allowlist (MIT, BSD, Apache-2.0, CC0, public domain); check the format and a size cap; rerun the generation script and compare the hash. Reviewers judge only the source's quality.
  - **Contribution path:** a "Wordlist contribution" issue template, a `CONTRIBUTING.md` section, and one `help wanted` + `good first issue` issue per wanted language.
  - **User-installed lists (not shipped):** also read wordlists from a user data folder (e.g. `~/.local/share/pdf2epub/wordlists/`), a `--wordlist PATH` option, and the system's Hunspell dictionaries (e.g. `/usr/share/hunspell/de_DE.dic`). Nothing is redistributed, so GPL, LGPL or MPL lists work locally. Precedence: option, user folder, shipped list, system Hunspell.
  - Recalibrate the text-layer thresholds per language on must-trust and must-reject samples.
- **Interfaces touched:** reflow (wordlist selection per language and lookup order), ocr (word-plausibility signal per language), cli (`--wordlist`), api (`ConversionOptions` wordlist path), testing (fixtures per language; CI wordlist checks).
- **AC sketch:** Given a German born-digital fixture with hard-hyphenated line ends, then words in the German wordlist are joined without the hyphen; given a German must-trust text layer, then no page is rejected; given a user-installed Hunspell `de_DE.dic` and no shipped German list, then the same de-hyphenation result.
- **Dependencies:** none (pairs well with automatic language detection in [Metadata heuristics](#metadata-heuristics)).

## OCR

### OCR engine extensions
- **Motivation:** v1 exposes a deliberately small OCR surface with one engine.
- **Behaviour and flags:**
  - `--ocr-engine` with an engine registry, added once a second engine exists. Apple Vision on macOS is the expected one, through the existing `OcrEngine` protocol and its capability flags.
  - `--ocr-words FILE`: a user lexicon.
  - Character whitelists or charsets, and region requests.
  - Recognition alternatives.
  - `--dewarp` for curved book scans.
  - `--split-spreads` for two-page scans.
  - `--ocr-max-megapixels`.
  - Named scan presets (e.g. `microfiche`, `newsprint`).
  - Confidence calibration estimated from agreement between attempts, if fixed per-engine mappings prove inadequate.
- **Interfaces touched:** ocr (`OcrRequest` gains fields additively; `OcrOptions` gains fields), cli (new flags), api (`ocr` report entry already names the engine).
- **AC sketch (per feature):**
  - Given a fake second engine, `--ocr-engine fake` routes all OCR attempts to it.
  - Given a two-page spread scan, `--split-spreads` yields pages in order.
- **Dependencies:** none for the protocol. Apple Vision needs the macOS app work, or a Swift helper.

### GPL preprocessing tools as optional external programs
- **Motivation:** unpaper and ScanTailor do excellent cleanup but are GPL.
- **Behaviour:** if installed, call them as separate programs (never linked) through an opt-in flag.
- **Interfaces touched:** ocr (preprocessing step), cli (opt-in flag), main (licensing note).
- **AC sketch:** Given unpaper on `PATH` and the opt-in flag, then preprocessing runs it and accuracy on degraded fixtures is no worse than without it.
- **Dependencies:** none.

## Core and CLI

### Parallel conversions (`-j/--jobs`)
- **Motivation:** big batches are slow when run one conversion at a time.
- **Behaviour:**
  - A worker pool with one reader thread per worker pipe feeding a single dispatcher queue, so the event sink is still called from one thread.
  - `BatchOptions.jobs` gets a memory-aware default; `batch_started.jobs` reports it.
  - Tesseract runs with `OMP_THREAD_LIMIT=1`.
  - Password prompts are deferred until all workers are idle.
  - Report order stays input order.
- **Interfaces touched:** api (`BatchOptions.jobs`; no schema change, because v1 is parallel-ready), batch (worker pool), cli (`-j`).
- **AC sketch:** Given 8 fixtures and `-j 4`, then events from different conversions interleave, each carries its `id`, the report lists them in input order, and results are identical to `-j 1`.
- **Dependencies:** none. Parallel page processing inside one conversion is a separate, later item.

### Per-file skip during a batch
- **Motivation:** a user watching a long batch may want to drop one stuck file without cancelling everything.
- **Behaviour:** `{"type":"skip","id":N}` on stdin in `--interactive` mode, and a key in the human TTY UI. The skipped conversion becomes `skipped` with a new info issue `skipped_by_user`.
- **Interfaces touched:** api (stdin message, issue code), batch, cli.
- **AC sketch:** Given a running batch, when skip is sent for the current file, then its worker stops, no EPUB is written, and the batch continues.
- **Dependencies:** none.

### Config file (`--config`, `~/.config/pdf2epub/config.toml`)
- **Motivation:** power users repeat the same flags.
- **Behaviour:** TOML with any CLI option; precedence is CLI > config file > defaults. Password values are **not** allowed in the config file; it may point to a password map.
- **Interfaces touched:** cli.
- **AC sketch:** Given a config setting `ocr_quality = "best"`, then conversions use `best` unless `--ocr-quality` is given.
- **Dependencies:** none.

### `--pages RANGE`
- **Motivation:** convert part of a book, or test settings on a few pages.
- **Behaviour:** only the listed pages are converted; page labels still come from the source.
- **Interfaces touched:** reflow, cli.
- **AC sketch:** Given `--pages 1-10,20`, then the EPUB contains exactly those 11 pages' content.
- **Dependencies:** none.

### Parallel page processing within a conversion
- **Motivation:** OCR-heavy books are slow even as one conversion.
- **Behaviour:** a process pool for the `analyse` and `ocr` stages inside one worker, bounded by a memory budget.
- **Interfaces touched:** reflow, ocr. Events stay ordered per page.
- **AC sketch:** output is byte-identical to sequential processing.
- **Dependencies:** parallel conversions (shared budget logic).

### `--debug-dir`
- **Motivation:** tuning heuristics needs visibility.
- **Behaviour:** dump per-page intermediate data (spans, blocks, classifications, furniture decisions, OCR attempts) plus overlay PNGs to a folder. It never contains password values.
- **Interfaces touched:** reflow, ocr, cli.
- **AC sketch:** Given `--debug-dir D`, then D has one overlay per page and no file contains a supplied password.
- **Dependencies:** none.

## Quality and tooling

### Quality-metrics corpus in CI
- **Motivation:** v1 measures OCR accuracy only on synthetic fixtures and checks the smoke set by eye.
- **Behaviour:** a scheduled (non-gating) workflow over a larger corpus, with tracked metrics:
  - Internet Archive scans paired with Project Gutenberg texts (character error rate);
  - a PubMed Central Open Access CC BY sample with JATS XML (paragraph and heading F1);
  - olmOCR-bench (ODC-BY);
  - DocLayNet (CDLA-Permissive).
  - SafeDocs and GovDocs1 for local-only robustness runs.
  - Never HathiTrust or Google Books bulk downloads, and never OmniDocBench (non-commercial licence).
  - Manifests and fetching follow the v1 smoke-set pattern ([testing](../specs/testing.md)).
- **Interfaces touched:** testing, CI.
- **AC sketch:** the workflow publishes metrics per run, and a regression of more than 1 point opens an issue.
- **Dependencies:** none.

### Required CI status check
- **Motivation:** in v1 the agent gates its own merges on green CI. Making CI a required check in the `main` ruleset enforces it for everyone.
- **Behaviour:** the PR workflow (lint, types, full-matrix tests, branch coverage ≥ 75%, epubcheck, AC-marker gate) becomes a required status check in the `main-protection` ruleset.
- **Interfaces touched:** repo settings, [`github.md`](../instructions/github.md).
- **AC sketch:** a PR with a failing test cannot be merged, admin bypass excepted.
- **Dependencies:** a stable CI runtime.

### Ace by DAISY accessibility audit
- **Motivation:** accessible output (`lang` set, alt text, heading order, page list).
- **Behaviour:** run Ace in CI on fixture outputs and fix what it reports. Image alt text comes from captions, else "Figure N".
- **Interfaces touched:** epub, testing.
- **AC sketch:** the fixture EPUBs pass Ace's basic checks with no violations.
- **Dependencies:** none.

## Platforms and distribution

### Windows support
- **Motivation:** v1 is best-effort on Windows.
- **Behaviour:**
  - Windows joins the CI matrix.
  - Paths, atomic renames and worker subprocess signals are handled on Windows: no SIGTERM, so `TerminateProcess`; Ctrl-C via console control events.
  - Tesseract install docs cover winget and the UB Mannheim builds.
- **Interfaces touched:** batch (isolation, interrupt), main (platforms).
- **AC sketch:** the full suite passes on Windows in CI, and Ctrl-C behaves as on Unix.
- **Dependencies:** none.

### Docker image
- **Motivation:** a one-command environment with Tesseract and language packs included.
- **Behaviour:**
  - A multi-arch image containing pdf2epub, Tesseract and common language packs.
  - The image runs with no network.
  - PDFium and Tesseract licence notices are included.
- **Interfaces touched:** packaging.
- **AC sketch:** `docker run … pdf2epub book.pdf` converts a scanned fixture with OCR.
- **Dependencies:** none.

### Rust port of the core
- **Motivation:** an option if performance or in-process embedding ever demands it ([ADR 0001](../adr/0001-python-core.md)).
- **Behaviour:**
  - Reimplement the core against the same `--json` wire protocol, so front ends are unaffected.
  - Use pdfium-render (never the GPL `pdfium` crate or the AGPL `mupdf` crate).
  - UniFFI bindings for Swift.
- **Interfaces touched:** everything behind the wire protocol; the protocol itself unchanged.
- **AC sketch:** the Python AC suite, run against the Rust CLI through the CLI seam, passes.
- **Dependencies:** a stable wire protocol (v1).

## Integrations

### Calibre plugin
- **Motivation:** many readers manage their libraries in Calibre.
- **Behaviour:** an input-format plugin that runs pdf2epub as a subprocess with `--json` and shows issues in Calibre's job log.
- **Interfaces touched:** none in the core; it is a front end.
- **AC sketch:** adding a PDF in Calibre with the plugin produces the same EPUB as the CLI.
- **Dependencies:** none.

### Watch-folder mode
- **Motivation:** drop PDFs in a folder and get EPUBs without running a command.
- **Behaviour:** `pdf2epub --watch DIR`. It converts new or changed PDFs once they are stable (size unchanged for N seconds), using the normal batch rules. Files needing passwords are reported and left alone.
- **Interfaces touched:** cli, batch (repeated planning).
- **AC sketch:** copying a fixture into the folder yields its EPUB within a minute; copying an encrypted one yields a `missing_password` report entry.
- **Dependencies:** none.

## GUI modes

Priority order. All three share:
- drag-and-drop batches;
- per-file password prompts (via `--json --interactive`, or defer-and-rerun);
- a batch report view built from `batch_finished`;
- metadata editing before conversion.

All drive the CLI's stable `--json` event stream as a subprocess ([api](../specs/api.md)).

### 1. Cross-platform desktop GUI (covers macOS)
- **Motivation:** a GUI for non-terminal users, macOS included, from one code base.
- **Behaviour:** a desktop app that bundles a frozen pdf2epub CLI helper (e.g. PyInstaller) and drives it through `--json --interactive`. Tauri, Flutter or Electron are all permissively licensed. Qt is flagged for its LGPL/commercial licensing and would need owner escalation.
- **Interfaces touched:** none in the core.
- **AC sketch:** dropping the mixed-batch fixture set onto the window shows each file's outcome and issues; a password prompt appears for the encrypted file; the report matches the CLI's.
- **Dependencies:** a frozen-helper build that ships PDFium notices ([main](../specs/main.md#main-r14)).

### 2. Local web UI
- **Motivation:** use from any browser on the same machine, or from a home server.
- **Behaviour:** a local HTTP front end, bound to localhost by default, wrapping the same event stream. If it ever needs its own API, that API gets its own spec.
- **Interfaces touched:** none in the core.
- **AC sketch:** uploading a fixture and downloading its EPUB works with no outbound network.
- **Dependencies:** none.

### 3. Native macOS port
- **Motivation:** the most native Mac experience.
- **Behaviour:**
  - A separate SwiftUI app driving the CLI's `--json` stream through a helper tool, sandboxed with only `app-sandbox` and `inherit`, via `Process`.
  - **Known risk:** whether the helper inherits file access that the app gains from open panels *after* launch needs a prototype. The documented fallback is XPC plus security-scoped bookmarks.
- **Interfaces touched:** none in the core.
- **AC sketch:** a notarized sandboxed app converts a user-chosen PDF via the helper and reports issues.
- **Dependencies:** a frozen CLI helper; the file-access prototype.
