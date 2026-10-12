# pdf2epub — Specification

Status: Draft v0.1 · 2026-10-12

## 1. Purpose

`pdf2epub` converts PDF files into valid, readable EPUB 3 books with as little
user effort as possible. The default path is one command with no flags:

```
pdf2epub book.pdf            # -> book.epub
```

The hard problem is not writing EPUB files — it is recovering *structure*
(paragraphs, headings, chapters, reading order) from a PDF, which only stores
positioned glyphs. Most of this spec is about doing that well and failing
gracefully when it can't be done.

## 2. Goals and non-goals

### Goals
- **G1 Easy:** sensible defaults; zero configuration for typical books.
- **G2 Reflowable output:** text that reflows on any e-reader screen size, with
  headings, paragraphs, emphasis, images, footnotes and a working table of
  contents.
- **G3 Valid output:** every produced EPUB passes `epubcheck` with zero errors.
- **G4 Graceful degradation:** when a page can't be reflowed sensibly (complex
  layouts, tables, math, comics), fall back to an image of that page rather
  than emitting garbage.
- **G5 Scanned PDFs:** optional OCR for image-only PDFs.
- **G6 Batch-friendly:** convert many files; scriptable; meaningful exit codes.
- **G7 Local and private:** runs fully offline; no files leave the machine.

### Non-goals (v1)
- Perfect fidelity for academic papers with heavy math, multi-column magazines,
  or data-dense tables. These get the fixed-layout/page-image fallback.
- Editing the book after conversion (users can use Sigil/Calibre).
- DRM removal. Encrypted PDFs require a user-supplied password; DRM-protected
  files are rejected.
- MOBI/AZW3 output (Kindle now accepts EPUB directly).

## 3. Users and use cases

| Persona | Use case |
|---|---|
| Casual reader | Drops a novel PDF in, gets an EPUB for their e-reader. |
| Power user | Batch-converts a library, tunes header/footer removal, sets metadata. |
| Archivist | Converts scanned books with OCR, keeps page-number mapping. |

## 4. Interfaces

### 4.1 CLI (primary, v1)

```
pdf2epub INPUT... [options]

Positional:
  INPUT                 One or more PDF files or directories (recursed with -r)

Output:
  -o, --output PATH     Output file (single input) or directory (multiple)
  --overwrite           Replace existing outputs (default: skip with warning)

Mode:
  --mode {auto,reflow,fixed}
                        auto (default): reflow, with per-page image fallback
                        reflow: always reflow, never fall back
                        fixed: EPUB 3 fixed-layout, one page image (+ hidden text) per page
  --ocr {auto,always,never}
                        auto (default): OCR pages with no extractable text
  --lang CODE           Document/OCR language, e.g. en, de, fra+eng (default: detect)

Structure:
  --pages RANGE         Only convert these pages, e.g. 1-200,305
  --toc {auto,outline,detect,none}
                        Source of chapters (default: auto = PDF outline if present, else detect)
  --split-level N       Heading level that starts a new XHTML file (default: 1)
  --strip-headers / --keep-headers
                        Remove running headers/footers/page numbers (default: strip)
  --no-images           Drop images
  --image-quality N     JPEG quality for re-encoded images (default: 85)
  --max-image-px N      Downscale images whose long edge exceeds N px (default: 1600)

Metadata (override what's detected):
  --title, --author (repeatable), --language, --publisher, --isbn, --date
  --cover PATH|first|none   Cover image (default: first page render if it looks like a cover)

Diagnostics:
  --report PATH         Write a JSON conversion report
  --debug-dir PATH      Dump intermediate data (blocks, classifications, overlay PNGs)
  -v / -q               Verbosity
  --config PATH         TOML file with any of the above options
```

**Exit codes:** `0` success · `1` partial success (some pages fell back or
warnings) when `--strict` is set, else `0` · `2` usage error · `3` input
unreadable/encrypted · `4` internal error. With multiple inputs, the highest
code wins; one failed file never aborts the batch.

### 4.2 Python library (v1)

```python
from pdf2epub import convert, Options
result = convert("book.pdf", "book.epub", Options(mode="auto", ocr="auto"))
result.warnings, result.fallback_pages, result.metadata
```

The CLI is a thin wrapper over this API.

### 4.3 GUI (v2, optional)
Drag-and-drop desktop/web UI over the same library: preview, metadata form,
chapter list editing before export. Out of scope for v1.

## 5. Conversion pipeline

```
PDF ─▶ 1 Load ─▶ 2 Extract ─▶ 3 OCR? ─▶ 4 Analyze layout ─▶ 5 Build document model
     ─▶ 6 Segment chapters ─▶ 7 Render XHTML/CSS ─▶ 8 Package EPUB ─▶ 9 Validate
```

Each stage is a pure function over a well-defined intermediate model, so stages
can be unit-tested and debugged independently (`--debug-dir` dumps each one).

### 5.1 Load
- Open the PDF; handle password (`--password`), detect DRM → exit 3.
- Read document metadata (Info dict + XMP), outline/bookmarks, page labels.
- Repair-tolerant: malformed PDFs should still open where the library allows.

### 5.2 Extract (per page)
Produce a list of **spans**: text, bbox, font name, size, weight/italic flags,
color, plus **images** (bbox, raw bytes) and **vector drawings** (for detecting
rules/tables). Text is normalized: Unicode NFC, ligatures (ﬁ→fi) expanded,
soft hyphens handled.

### 5.3 OCR (conditional)
- A page needs OCR if it has < N extractable characters but ≥ 1 large image, or
  if extracted text is mostly invalid (e.g. broken font encodings → mojibake
  ratio above threshold).
- Render the page at 300 DPI, run Tesseract (hOCR/TSV output), convert results
  into the same span model (font size estimated from line height; no styling).

### 5.4 Layout analysis
Per page, turn spans into ordered **blocks**:
1. Group spans → lines → blocks using geometry (baseline, line spacing, x-gaps).
2. Detect columns (x-projection histogram) and establish reading order
   (column-major, top-to-bottom).
3. **Furniture removal:** find running headers, footers and page numbers by
   comparing top/bottom bands across pages (repeated text, or text matching a
   page-number pattern, at a consistent position). Remove when `--strip-headers`.
4. Classify each block: `heading(level)`, `paragraph`, `list_item`,
   `blockquote`, `footnote`, `caption`, `image`, `table`, `code/preformatted`,
   `unknown`.
   - Body font size = the mode of span sizes weighted by character count.
     Headings = larger/bolder than body, short, followed by spacing; levels
     assigned by clustering distinct heading styles.
   - Footnotes = small font, bottom of page, starts with a marker matching a
     superscript reference in the body.
5. **Page complexity score** (0–1) from: number of columns, fraction of area
   that is images/vector graphics, table-like grid density, math glyph ratio,
   unclassified block ratio. In `auto` mode, pages above a threshold (default
   0.6) fall back to a page image (see 5.7).

### 5.5 Document model
Merge pages into one stream of blocks and repair page-break artifacts:
- **Paragraph continuation:** a paragraph that ends a page without terminal
  punctuation and the next page starts with a lowercase/continuation is joined.
- **De-hyphenation:** join `exam-\nple` → `example` when the joined word is in a
  dictionary/word-frequency list (or the hyphen was a soft hyphen); otherwise
  keep the hyphen.
- **Line joining:** lines within a paragraph join with spaces (CJK: no space).
- Inline styling: runs of bold/italic/superscript/small-caps become inline
  marks. Superscript numbers linked to footnotes become note references.
- Retain page-break markers (`<span epub:type="pagebreak" id="page_N">`) using
  PDF page labels so citations to print page numbers still work.

Model (simplified):
```
Document{ metadata, cover, blocks: [Block], toc: [TocEntry] }
Block   = Heading{level, inlines, id} | Paragraph{inlines} | ListItem{...}
        | Image{asset, caption} | Footnote{id, blocks} | PageImage{page}
        | PageBreak{label} | Table{rows} | Pre{text}
Inline  = Text{str, marks:{bold,italic,sup,sub,smallcaps}} | Link{href, inlines} | NoteRef{id}
```

### 5.6 Chapter segmentation and TOC
- `outline`: use PDF bookmarks; map each bookmark's destination to the first
  block at/after that point and insert a split there. Bookmark titles become TOC
  entries; nested bookmarks become nested TOC.
- `detect`: use classified headings; level ≤ `--split-level` starts a new file.
  Also detect patterns like "Chapter 7", "CHAPTER SEVEN", "Part II".
- `auto`: outline if it has ≥ 3 entries that resolve to pages, else detect.
- Front matter heuristics: title page, copyright page, dedication, contents
  page. The printed "Contents" page is dropped when a real TOC was generated
  (configurable).
- Guarantee: each XHTML file ≤ ~300 KB; oversize chapters are split at
  paragraph boundaries (some readers struggle with huge files).

### 5.7 Rendering
- One XHTML5 file per chapter; semantic markup (`<h1>`–`<h6>`, `<p>`,
  `<aside epub:type="footnote">`, `<figure>/<figcaption>`, `<a epub:type="noteref">`).
- A small default stylesheet: relative units only (`em`, `%`), no fixed fonts or
  colors, so reader settings (font, size, night mode) work.
- Footnotes: placed at end of chapter as `<aside epub:type="footnote">` with
  back-links (pop-up footnotes on readers that support them).
- Images: extracted at native resolution, downscaled to `--max-image-px`,
  re-encoded (JPEG for photos, PNG for line art), deduplicated by hash.
  Decorative repeating images (logos in headers) are dropped.
- **Page-image fallback:** render the page to an image (~1600px long edge),
  embed as a full-width `<figure>`; include the extracted text as visually
  hidden alt text / an accessible description so it remains searchable.
- `fixed` mode: EPUB 3 fixed-layout (`rendition:layout=pre-paginated`), one
  page image per spine item with an invisible text layer.

### 5.8 Packaging
EPUB 3.3 container:
- `mimetype` (first, stored uncompressed), `META-INF/container.xml`,
  `OEBPS/content.opf`, `nav.xhtml` (TOC + page-list + landmarks), `toc.ncx`
  (EPUB 2 back-compat for older readers), XHTML, CSS, images, cover.
- Metadata: `dc:title`, `dc:creator`, `dc:language` (required — detected via
  language ID if missing), `dc:identifier` (ISBN if found/given, else a
  deterministic UUIDv5 from the file hash), `dcterms:modified`.
- Cover: `cover-image` property + a cover XHTML page.
- Deterministic output: the same input + options produce a byte-identical
  EPUB (fixed zip timestamps, sorted entries) — useful for tests and caching.

### 5.9 Validation
- Run `epubcheck` when available (`--validate`, on by default in tests/CI).
- Always run built-in checks: well-formed XHTML, all manifest items exist, all
  internal links resolve, spine non-empty.

## 6. Metadata detection
Priority order: CLI flags > config file > XMP > PDF Info dict > title-page
heuristics (largest text on first pages → title; "by X" → author) > filename
(`Author - Title.pdf` pattern). ISBN: regex + checksum validation on the first
and last ~10 pages.

## 7. Conversion report
`--report out.json` emits per-file: detected metadata, chapter list, pages
reflowed vs. fell back (with complexity scores and reasons), OCR'd pages,
removed headers/footers samples, warnings, timing, epubcheck results. The CLI
prints a one-line summary per file, e.g.
`book.pdf → book.epub · 312 pages · 24 chapters · 3 pages as images · 4.1s`.

## 8. Non-functional requirements

| Area | Requirement |
|---|---|
| Performance | ≥ 20 pages/s for text PDFs on a laptop; OCR bounded by Tesseract (~1–3 s/page). Pages processed in parallel (process pool). |
| Memory | Streams page by page; peak < 500 MB for a 1,000-page book. |
| Robustness | No crash on malformed input; a failure on one page degrades that page to an image, never the whole book. |
| Portability | Linux, macOS, Windows. Python ≥ 3.10. |
| Install | `pipx install pdf2epub`; OCR needs Tesseract installed separately (clear error message if missing). Docker image includes everything. |
| Security | Treat PDFs as untrusted: no JavaScript execution, no network access, size/time limits per page, decompression-bomb limits on images. |
| Privacy | Fully offline. No telemetry. |
| Accessibility | Output passes Ace by DAISY basic checks: `lang` set, images have alt text (captions or "Figure N"), logical heading order, page-list present. |

## 9. Technology choices

| Concern | Choice | Notes |
|---|---|---|
| Language | Python 3.10+ | Best PDF/OCR ecosystem. |
| PDF parsing & rendering | **PyMuPDF (fitz)** | Fast, rich span/font info, rendering, outlines. **AGPL-3.0** → project must be AGPL or buy a license. Alternative: `pypdfium2` (render, Apache/BSD) + `pdfminer.six` (text, MIT) — slower, more code. See open question Q1. |
| OCR | Tesseract via `pytesseract` | Optional extra: `pip install pdf2epub[ocr]`. |
| Language detection | `lingua` or `langdetect` | For `dc:language` when missing. |
| EPUB writing | Own small writer (zipfile + Jinja2 templates) | `ebooklib` is an option, but owning the writer makes deterministic output and EPUB 3 nav/page-list easier. |
| Images | Pillow | |
| CLI | `typer` (or `argparse` to stay dependency-light) | |
| Config | TOML (`tomllib`) | |
| Validation | `epubcheck` (Java) in CI; optional at runtime | |
| Testing | pytest, golden-file tests, hypothesis for model invariants | |

## 10. Project layout

```
pdf2epub/
  src/pdf2epub/
    __init__.py         # convert(), Options
    cli.py
    options.py
    load.py             # 5.1
    extract.py          # 5.2  -> spans
    ocr.py              # 5.3
    layout/
      blocks.py         # spans -> lines -> blocks
      columns.py        # reading order
      furniture.py      # headers/footers/page numbers
      classify.py       # block types, heading levels
      complexity.py     # fallback scoring
    model.py            # Document/Block/Inline dataclasses
    assemble.py         # 5.5 cross-page repair, dehyphenation
    segment.py          # 5.6 chapters + TOC
    metadata.py         # 6
    render/
      xhtml.py          # 5.7
      images.py
      templates/        # Jinja2 XHTML/OPF/nav/ncx
      default.css
    package.py          # 5.8
    validate.py         # 5.9
    report.py           # 7
  tests/
    fixtures/           # small generated + public-domain PDFs
    golden/             # expected model JSON / XHTML snapshots
  docs/
  pyproject.toml
```

## 11. Testing strategy
- **Unit:** each layout heuristic on synthetic span lists (no PDFs needed).
- **Fixture PDFs:** generated with ReportLab/LaTeX/Typst so ground truth is
  known — single column, two columns, footnotes, running headers, hyphenation,
  images, outline vs. no outline, scanned (rendered-to-image) variants.
- **Real-world corpus:** ~20 public-domain books (Project Gutenberg / Internet
  Archive / arXiv CC-BY papers) with golden snapshots of the document model.
- **Validation:** every test EPUB goes through `epubcheck`; zero errors required.
- **Quality metrics** (tracked in CI over the corpus): character-level accuracy
  vs. ground-truth text, paragraph-boundary F1, heading detection F1, % pages
  fallen back. Regressions beyond a tolerance fail the build.
- **Fuzz/robustness:** malformed PDFs (e.g. from a PDF fuzz corpus) must not crash.

## 12. Acceptance criteria for v1
1. `pdf2epub novel.pdf` on a single-column text novel yields an EPUB that
   passes epubcheck, has correct chapters in the TOC, no running headers/page
   numbers in the text, no mid-paragraph breaks at page boundaries, and
   ≥ 99.5% character accuracy.
2. A scanned book converts with `--ocr auto` without extra flags.
3. A two-column paper produces correct reading order or falls back per page —
   never interleaved columns.
4. Batch of 100 PDFs completes; a corrupt file is reported, not fatal.
5. Output opens correctly in Apple Books, Kobo, Calibre viewer, Thorium, and
   Kindle (via Send to Kindle).

## 13. Open questions
- **Q1 License:** accept AGPL (PyMuPDF) or use permissive stack
  (pypdfium2 + pdfminer.six)? *Default assumption: PyMuPDF/AGPL.*
- **Q2** Tables: reflow as HTML `<table>` in v1, or always image-fallback?
  *Default: image fallback in v1, HTML tables in v2.*
- **Q3** Math: image fallback for equations vs. MathML via an external model?
  *Default: per-block image of the equation region.*
- **Q4** Should an optional ML layout model (e.g. a document-layout detector)
  be offered as a plugin for hard documents? *Default: v2 plugin interface.*
- **Q5** GUI form factor: desktop (Tauri/Qt) vs. local web UI? *Defer to v2.*
