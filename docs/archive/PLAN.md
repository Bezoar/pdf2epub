# pdf2epub — Implementation Plan

Companion to [SPEC.md](SPEC.md). Work is split into milestones that each end
with something usable, so quality can be measured early and heuristics tuned
against real books.

## Milestone 0 — Project skeleton (≈1–2 days)
- [ ] `pyproject.toml` (hatch or uv), `src/` layout, ruff, mypy, pytest, pre-commit.
- [ ] CI (GitHub Actions): lint, typecheck, tests on Linux/macOS/Windows, Python 3.10–3.13.
- [ ] Install `epubcheck` in CI; helper `assert_valid_epub(path)`.
- [ ] Fixture generator script (ReportLab/Typst) producing the synthetic PDFs from SPEC §11.
- [ ] Decide Q1 (license) — it determines the PDF library.

**Done when:** `pytest` runs green in CI with a placeholder test.

## Milestone 1 — Walking skeleton: naive but valid (≈3–4 days)
Goal: end-to-end PDF → valid EPUB, even if structure is crude.
- [ ] `model.py` dataclasses + JSON (de)serialization (for golden tests/debug).
- [ ] `load.py`: open, password, metadata, outline, page labels.
- [ ] `extract.py`: spans with font/size/flags/bbox; ligature/Unicode normalization.
- [ ] Naive blocks: one paragraph per PyMuPDF text block.
- [ ] `render/xhtml.py` + templates + `default.css`.
- [ ] `package.py`: OPF, nav.xhtml, toc.ncx, cover, deterministic zip.
- [ ] `cli.py` with `INPUT`, `-o`, `--title/--author`, `-v`.
- [ ] One chapter per PDF outline entry (or one file per N pages if no outline).

**Done when:** every fixture converts and passes epubcheck; opens in Calibre and Thorium.

## Milestone 2 — Good reflow for simple books (≈1–2 weeks) ← core value
- [ ] `layout/blocks.py`: spans → lines → paragraphs using line spacing and indent.
- [ ] `layout/furniture.py`: cross-page header/footer/page-number detection and removal.
- [ ] `layout/classify.py`: body-size detection, heading detection + level clustering,
      lists, blockquotes, captions.
- [ ] `assemble.py`: cross-page paragraph joining, de-hyphenation (word list), inline
      bold/italic/superscript marks, page-break markers from page labels.
- [ ] `segment.py`: `--toc auto|outline|detect|none`, "Chapter N" patterns, front-matter
      handling, file size cap.
- [ ] `metadata.py`: priority chain, ISBN detection, language detection, filename parsing.
- [ ] `render/images.py`: extract, dedupe, downscale, re-encode, drop decorative repeats.
- [ ] Footnotes: detection, noteref linking, `<aside epub:type="footnote">`.
- [ ] Quality harness: corpus of ~20 public-domain books + metrics script
      (char accuracy, paragraph F1, heading F1) and golden snapshots.

**Done when:** acceptance criterion #1 met on the novel-type corpus; metrics are baselined in CI.

## Milestone 3 — Hard layouts & graceful fallback (≈1 week)
- [ ] `layout/columns.py`: column detection, reading order.
- [ ] `layout/complexity.py`: page complexity score; `--mode auto` per-page image fallback
      with hidden searchable text.
- [ ] `--mode fixed`: EPUB 3 pre-paginated output.
- [ ] Equation/table regions → cropped region images (Q2/Q3 defaults).
- [ ] `--debug-dir`: overlay PNGs coloring blocks by class + JSON dumps per stage.

**Done when:** acceptance criterion #3 met; no interleaved-column output across the corpus.

## Milestone 4 — OCR (≈3–5 days)
- [ ] `ocr.py`: needs-OCR detection (no text / mojibake ratio), 300-DPI render,
      Tesseract TSV → spans; `--ocr`, `--lang`.
- [ ] Graceful message when Tesseract or language data is missing.
- [ ] Scanned fixtures (render text fixtures to images, add noise/skew) + accuracy tests.

**Done when:** acceptance criterion #2 met.

## Milestone 5 — Usability, batch & performance (≈1 week)
- [ ] Multiple inputs, directories (`-r`), `--overwrite`, exit codes, `--strict`.
- [ ] Per-page parallelism (process pool) for extract/OCR; streaming to bound memory.
- [ ] `--report` JSON + one-line summaries + progress bar.
- [ ] `--config` TOML; `--pages`; image options.
- [ ] Robustness: per-page try/except → page-image fallback; per-page time/size limits;
      fuzz test with malformed PDFs.
- [ ] Benchmarks: pages/s and peak memory on a 1,000-page book in CI (tracked, not gating).

**Done when:** acceptance criterion #4 met; performance targets in SPEC §8 met.

## Milestone 6 — Release v1.0 (≈3–4 days)
- [ ] Device testing: Apple Books, Kobo, Kindle (Send to Kindle), Calibre, Thorium (criterion #5).
- [ ] Accessibility check with Ace by DAISY.
- [ ] README with examples & limitations, `--help` polish, CHANGELOG.
- [ ] Publish to PyPI (trusted publishing), Docker image with Tesseract + common languages.

## Later (v2 candidates)
- HTML table reconstruction; MathML for equations.
- Plugin interface for ML layout models (better headings, tables, reading order).
- GUI: preview pages with block overlays, edit chapter list & metadata, then export.
- Watch-folder / Calibre plugin integration.

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| Heuristics overfit a few books | Diverse corpus + metrics in CI; tune against the corpus, not single files. |
| PDFs with broken font encodings (garbled text) | Mojibake detection → OCR that page. |
| Heading detection is noisy | Prefer PDF outline when present; conservative thresholds; `--toc none` escape hatch. |
| AGPL licensing constraint | Decide Q1 in M0; isolate PDF access behind `extract.py`/`load.py` so the backend can be swapped. |
| Reader-specific rendering quirks | Minimal CSS, relative units, test on real devices before release. |

## Rough total
≈ 6–8 weeks for one developer to v1.0; M1–M2 (≈2–3 weeks) already give a
useful tool for ordinary text-based books.
