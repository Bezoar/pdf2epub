# OCR

**Status:** draft · **Depends on:** [main](main.md), [api](api.md), [reflow](reflow.md), [batch](batch.md), [passwords](passwords.md) · **Decisions:** [v1 scope cut and roadmap contents](https://github.com/Bezoar/pdf2epub/issues/6), [OCR engine tuning surface](https://github.com/Bezoar/pdf2epub/issues/12), [OCR engine interface design](https://github.com/Bezoar/pdf2epub/issues/13), [Text-layer quality check](https://github.com/Bezoar/pdf2epub/issues/15), [ADR 0001](../adr/0001-python-core.md)

This spec covers how text is obtained from pages: deciding which pages need OCR, the text-layer quality check that decides whether an existing text layer is trusted, the `OcrEngine` protocol and its Tesseract adapter, image cleanup before OCR, the acceptance test and retry ladder, OCR options, and the OCR issues. It does not cover what happens to the recognised text afterwards (furniture, page joins, de-hyphenation, headings: see [reflow](reflow.md)), how a fallback page is marked up (see [epub](epub.md)), or the issue registry and event shapes (see [api](api.md)). Flag names are mapped in [cli](cli.md).

## 1. Page routing

<a id="ocr-r1"></a>**OCR-R1**: Under `OcrOptions.mode = "auto"`, the core shall route each page by its content:
- a page with no text layer (or almost none) and an image covering a large share of the page shall be OCR'd directly, without the text-layer quality check;
- a page with no text and no significant image shall be treated as blank: no OCR and no issue;
- every other page with a text layer shall go through the text-layer quality check ([§2](#2-text-layer-quality-check)); it is OCR'd only if the check rejects it.

<a id="ocr-r2"></a>**OCR-R2**: Under `OcrOptions.mode = "always"`, the core shall OCR every page that is not blank, whatever text layer it has. Its per-page `ocr` progress event shall carry `trigger: "forced"`.

<a id="ocr-r3"></a>**OCR-R3**: Under `OcrOptions.mode = "never"`, the core shall never run the OCR engine. It still runs the text-layer quality check. A page whose text layer is rejected, and a page that would have been OCR'd directly, shall become a [page-image fallback](reflow.md) with a [`page_fallback`](api.md#code-page_fallback) issue whose reason is `bad_text_layer`. Garbage text is never emitted.

<a id="ocr-r4"></a>**OCR-R4**: Each OCR'd page's `ocr` progress event shall carry `trigger`, one of `no_text_layer` (routed directly by [OCR-R1](#ocr-r1)), `text_layer_rejected` (the check rejected its layer) or `forced` ([OCR-R2](#ocr-r2)). Under `mode = "auto"`, pages whose text layer is trusted get no `ocr` event and no issue; under `mode = "always"`, every non-blank page is OCR'd and gets its `forced` event ([OCR-R2](#ocr-r2)).

## 2. Text-layer quality check

<a id="ocr-r5"></a>**OCR-R5**: The text-layer quality check shall decide **per page**. A font-level fault, such as a font with no usable Unicode map, shall count against every page that uses that font. This keeps the book consistent without a separate document-level verdict.

<a id="ocr-r6"></a>**OCR-R6**: The check shall classify each text layer as a **typeset text layer** (visible text drawn in fonts) or a **prior OCR layer** (invisible text, i.e. PDF text render mode 3, or text lying over an image that covers the full page), using PDFium's text render mode and the page's image objects.

<a id="ocr-r7"></a>**OCR-R7**: The check shall compute these signals, and reject the page if **any** active signal crosses its threshold:
1. **Garbage ratio** (always active, works for any language): the share of characters that are PDFium Unicode-map errors, U+FFFD, Private Use Area code points, C0/C1 control characters, or characters from a script that does not match the OCR language.
2. **Word plausibility** (always active): the share of tokens found in the wordlist that de-hyphenation uses ([reflow](reflow.md)). If the language has no wordlist, it is the share of tokens that look like words (letters only, sensible length). A page is never rejected just because a wordlist is missing.
3. **Text-layer coverage** (prior OCR layers only): the [coverage](#ocr-r16) metric applied to the existing layer's character boxes against ink in the rendered page. It catches partial and misaligned layers.

Font names, Producer/Creator strings and guesses about which OCR engine made a layer shall not be used as signals.

<a id="ocr-r8"></a>**OCR-R8**: The check's thresholds shall be internal constants with no option or flag. They shall be calibrated so that every **must-trust** fixture passes and every **must-reject** fixture fails ([TST](testing.md)). Both sets are regression tests. The escape hatches are `mode = "always"` and `mode = "never"`.

<a id="ocr-r9"></a>**OCR-R9**: For each conversion, rejected pages shall be reported as [`text_layer_rejected`](api.md#code-text_layer_rejected) (info), grouped as one issue per reason with a sorted page list. Reasons are `garbled` (garbage ratio), `implausible_words` (word plausibility) or `low_coverage` (text-layer coverage). If several signals fail on a page, the reason is the first in that order.

<a id="ocr-r10"></a>**OCR-R10**: Under `mode = "auto"`, a rejected page shall be re-OCR'd through the [retry ladder](#4-preprocessing-acceptance-and-retry-ladder). If attempts completed but none was accepted, the page becomes a page-image fallback with reason `ocr_low_confidence`. If the ladder ended because the page budget ran out or the engine failed, the reason is set by [OCR-R22](#ocr-r22) or [OCR-R23](#ocr-r23) instead. In every case the fallback's hidden searchable text shall be whichever of the best OCR attempt and the original text layer scores better on the signals in [OCR-R7](#ocr-r7), except that a layer rejected as `garbled` is never used, and when every OCR attempt returned no words, [OCR-R31](#ocr-r31) applies instead (the rejected layer is never used). If nothing is usable, the page image has no hidden text.

## 3. Engine protocol and Tesseract adapter

<a id="ocr-r11"></a>**OCR-R11**: The core shall define one `OcrEngine` protocol with two operations:
- `capabilities() -> Capabilities`, where `Capabilities` gives the granularities supported, the confidence scale, whether the engine has orientation detection (OSD), and the engine's licence;
- `recognise(request: OcrRequest) -> OcrPageResult`.

v1 has exactly one adapter, for Tesseract. There is no engine registry and no engine-selection option (roadmap: a second engine, likely Apple Vision).

<a id="ocr-r12"></a>**OCR-R12**: `OcrRequest` shall carry `image` (the cleaned page image), `dpi`, `languages` (Tesseract language codes, e.g. `eng+deu`), `layout_hint` (one of `PAGE`, `BLOCK`, `LINE`, `SPARSE`, which the adapter maps to a Tesseract page segmentation mode), `deadline` (an absolute time by which the attempt must finish) and `engine_options` (a string-to-string map passed through to the engine).

<a id="ocr-r13"></a>**OCR-R13**: `OcrPageResult` shall contain:
- lines, each made of words; each word has a bounding box in page coordinates (origin top-left), a confidence normalised to [0, 1] and the engine's raw confidence; each line has its line height (used for heading inference in [reflow](reflow.md));
- `page_confidence`: the mean word confidence weighted by word length;
- `coverage`: see [OCR-R16](#ocr-r16);
- `warnings`: engine diagnostics as text;
- `attempts`: one record per OCR attempt, with the variant used, its confidence, coverage and duration.

Results are word-level: no character-level detail and no alternative readings.

<a id="ocr-r14"></a>**OCR-R14**: The Tesseract adapter shall run the `tesseract` program as a separate subprocess **for each OCR attempt**, read its TSV output with an in-house parser, and kill the process when the attempt's deadline passes. It shall not use pytesseract or tesserocr. A Tesseract crash or hang costs at most that one page. The subprocess shall run with `OMP_THREAD_LIMIT=1`, and with every password environment variable removed ([passwords](passwords.md) owns the variable list).

<a id="ocr-r15"></a>**OCR-R15**: The adapter shall normalise confidence with a fixed mapping (Tesseract's raw word confidence ÷ 100). Thresholds are tuned against that mapping. OCR confidence values are only comparable within one engine.

<a id="ocr-r16"></a>**OCR-R16**: The pipeline, not the engine, shall compute **coverage**: the share of the page's ink pixels (from the binarised image) that fall inside the bounding boxes of recognised words. It catches dropped text that OCR confidence misses.

<a id="ocr-r17"></a>**OCR-R17**: An empty OCR result (no words) on a page **with no text layer** shall not be an issue: such pages are blank or illustrations. The page keeps its rendered image if it has a significant image ([reflow](reflow.md) decides), and otherwise contributes no text.

## 4. Preprocessing, acceptance and retry ladder

<a id="ocr-r18"></a>**OCR-R18**: The pipeline shall own image cleanup, using OpenCV, in this order: orientation correction, deskew, border crop, rescale to about 300 DPI, binarisation, denoise. Tesseract's OSD may be used only as the orientation **detector**, and only when the engine's capabilities say it has OSD. The un-cleaned page render shall be kept for page-image fallback.

<a id="ocr-r19"></a>**OCR-R19**: An OCR attempt is **accepted** when `coverage ≥ c_min` **and** `page_confidence ≥ p_min`. `c_min` is an internal constant. `p_min` is an internal constant unless `OcrOptions.min_confidence` is set, which replaces it.

<a id="ocr-r20"></a>**OCR-R20**: Under the default quality (`balanced`), the core shall run the retry ladder below, stopping at the first accepted attempt:
1. Baseline: layout hint `PAGE` (Tesseract psm 3), Otsu binarisation.
2. If coverage was below `c_min`: layout hint `BLOCK` (psm 6).
3. If confidence was below `p_min`: Sauvola binarisation.
4. If confidence is still below `p_min`: Sauvola plus denoise.

The ladder shall keep the best attempt, ranked by coverage first and then confidence. If attempts completed but none was accepted, the page becomes a page-image fallback with reason `ocr_low_confidence` (timeouts and engine failures take the reasons in [OCR-R22](#ocr-r22) and [OCR-R23](#ocr-r23)), and all attempts are recorded in the result. There is no voting between attempts and no second engine.

<a id="ocr-r21"></a>**OCR-R21**: `OcrOptions.quality` sets how deep the ladder goes:
- `fast`: the baseline attempt only;
- `balanced` (default): the full ladder of [OCR-R20](#ocr-r20), stopping at the first accepted attempt;
- `best`: all four ladder steps, **unconditionally**: the conditions in [OCR-R20](#ocr-r20) steps 2–4 are ignored and nothing stops early except the page budget ([OCR-R22](#ocr-r22)). The best attempt by (coverage, confidence) is kept.

Model choice is separate: it comes from `OcrOptions.tessdata_dir` (e.g. a tessdata_best folder).

<a id="ocr-r22"></a>**OCR-R22**: `OcrOptions.page_timeout` (default **180 seconds**) is the budget for a whole page across the ladder. Each attempt's deadline is the time remaining in that budget. When the budget runs out, the ladder stops: the best attempt so far is used if it is accepted, otherwise the page falls back with reason `ocr_timeout`, and the page is listed in an [`ocr_timeout`](api.md#code-ocr_timeout) issue (warning).

<a id="ocr-r23"></a>**OCR-R23**: If Tesseract crashes or exits with a non-zero status on an attempt, that attempt shall count as failed and the ladder shall continue. If no attempt on the page succeeds because of such failures, the page falls back with reason `ocr_failed`, and the page is listed in an [`ocr_failed`](api.md#code-ocr_failed) issue (warning).

## 5. Availability and options

<a id="ocr-r24"></a>**OCR-R24**: The core shall probe the Tesseract program and its installed languages **once**, in the run's preflight ([API-R29](api.md#api-r29)). Each conversion's OCR languages, including any taken from PDF metadata ([OCR-R26](#ocr-r26)), are checked against that list when the conversion starts, without probing again. Each conversion that would need OCR shall then carry one [`ocr_unavailable`](api.md#code-ocr_unavailable) issue (warning, no page list), with a hint that names the per-platform install command (e.g. `brew install tesseract tesseract-lang`, `apt install tesseract-ocr tesseract-ocr-<lang>`). Pages that need OCR fall back with reason `ocr_unavailable`. A missing engine is never fatal to a conversion or a batch.

<a id="ocr-r25"></a>**OCR-R25**: When the preflight's engine probe ([OCR-R24](#ocr-r24)) finds Tesseract, the core shall validate every `OcrOptions.engine_options` key against the output of `tesseract --print-parameters` in the run's preflight ([API-R29](api.md#api-r29)), before any event is emitted. When Tesseract is missing, the options cannot be validated: they are ignored, and conversions get [`ocr_unavailable`](api.md#code-ocr_unavailable) as OCR-R24 says. An unknown key is a usage error: nothing runs and the exit code is 2 ([batch](batch.md)). Keys are namespaced by engine (`tesseract.KEY`); the namespace is stripped before passing them on.

<a id="ocr-r26"></a>**OCR-R26**: The OCR language shall be chosen in this order: `OcrOptions.languages` if set; else `ConversionOptions.language` ([reflow](reflow.md)) mapped to its Tesseract code; else the language in the PDF's metadata, mapped likewise; else `eng`.

<a id="ocr-r27"></a>**OCR-R27**: The core shall define `OcrOptions` as frozen plain data with these fields and defaults:

| Field | Meaning | Default |
|---|---|---|
| `mode` | `auto`, `always` or `never` ([§1](#1-page-routing)) | `auto` |
| `languages` | Tesseract language string, e.g. `eng+fra` ([OCR-R26](#ocr-r26)) | none (derived) |
| `quality` | `fast`, `balanced` or `best` ([OCR-R21](#ocr-r21)) | `balanced` |
| `page_timeout` | seconds per page across the ladder ([OCR-R22](#ocr-r22)) | 180 |
| `min_confidence` | replaces `p_min`, 0 to 1 ([OCR-R19](#ocr-r19)) | none (internal `p_min`) |
| `engine_options` | `tesseract.KEY` → value passthrough ([OCR-R25](#ocr-r25)) | empty |
| `tesseract_path` | path to the `tesseract` program | none (found on `PATH`) |
| `tessdata_dir` | folder of language models | none (Tesseract's own) |

The coverage threshold, the ladder's steps and the render DPI are internal constants, not options. Front ends resolve environment variables (e.g. `PDF2EPUB_TESSERACT`) into these fields ([cli](cli.md)).

## 6. Recognised text, events and report

<a id="ocr-r28"></a>**OCR-R28**: OCR'd text shall be treated as single-column. Bold and italic shall not be detected in OCR'd text. Headings are inferred from line height and position ([reflow](reflow.md)).

<a id="ocr-r29"></a>**OCR-R29**: Each OCR'd page shall emit one `progress` event with stage `ocr` ([api](api.md)) carrying `confidence` (the kept attempt's page confidence), `coverage`, `attempts` (the number of attempts run), `fell_back` (true if the page became a page image) and `trigger` ([OCR-R4](#ocr-r4)).

<a id="ocr-r30"></a>**OCR-R30**: Each conversion's result shall carry `ocr: {engine, engine_version, languages, quality}` when it OCR'd at least one page, and `ocr: null` otherwise. Nothing about OCR shall be written into the EPUB's metadata.

<a id="ocr-r31"></a>**OCR-R31**: An empty OCR result on a page that **has** a text layer (possible under `mode = "always"`, or after the layer was rejected) shall never silently drop that text. If the layer passes the text-layer quality check ([OCR-R7](#ocr-r7)), the page keeps it as its text. Otherwise the page becomes a page-image fallback with reason `ocr_low_confidence` and **no** hidden searchable text: the layer failed the check, so using it would reintroduce the garbage the check exists to keep out.

## 7. Acceptance criteria

All page images below are synthetic fixtures from [testing](testing.md) unless named otherwise. "Fake engine" means a test double at the `OcrEngine` seam that returns scripted results.

<a id="ocr-ac1"></a>**OCR-AC1** (covers [OCR-R1](#ocr-r1), [OCR-R4](#ocr-r4)): **Given** an image-only scanned fixture of 3 pages and `mode = "auto"` with the fake engine, **when** the conversion runs, **then** the fake engine is called for all 3 pages, each page's `ocr` event has `trigger: "no_text_layer"`, and no `text_layer_rejected` issue is reported.

<a id="ocr-ac2"></a>**OCR-AC2** (covers [OCR-R1](#ocr-r1), [OCR-R17](#ocr-r17)): **Given** a born-digital fixture with one blank page (no text, no image) and `mode = "auto"`, **when** it converts, **then** the fake engine is never called for the blank page, and the conversion's issues contain no OCR issue for it.

<a id="ocr-ac3"></a>**OCR-AC3** (covers [OCR-R1](#ocr-r1), [OCR-R5](#ocr-r5), [OCR-R7](#ocr-r7), [OCR-R8](#ocr-r8)): **Given** every must-trust fixture (born-digital typeset pages and pages with a good prior OCR layer), **when** the text-layer quality check runs, **then** every page is trusted: no `text_layer_rejected` issue, no `ocr` event, and the engine is not called.

<a id="ocr-ac4"></a>**OCR-AC4** (covers [OCR-R5](#ocr-r5), [OCR-R7](#ocr-r7), [OCR-R9](#ocr-r9)): **Given** the must-reject fixture whose font has no ToUnicode map (on pages 1–4), **when** it converts under `auto`, **then** a single `text_layer_rejected` issue with severity `info`, reason `garbled` and pages `[1, 2, 3, 4]` is reported.

<a id="ocr-ac5"></a>**OCR-AC5** (covers [OCR-R6](#ocr-r6), [OCR-R7](#ocr-r7), [OCR-R9](#ocr-r9)): **Given** the must-reject fixture with an invisible (render mode 3) OCR layer covering only the top half of each scanned page, **when** it converts under `auto`, **then** it reports `text_layer_rejected` with reason `low_coverage` for those pages, and their `ocr` events have `trigger: "text_layer_rejected"`.

<a id="ocr-ac6"></a>**OCR-AC6** (covers [OCR-R7](#ocr-r7), [OCR-R9](#ocr-r9)): **Given** the must-reject fixture with a garbled invisible OCR layer (valid characters, nonsense words), **when** it converts under `auto`, **then** it reports `text_layer_rejected` with reason `implausible_words` for those pages.

<a id="ocr-ac7"></a>**OCR-AC7** (covers [OCR-R7](#ocr-r7)): **Given** a typeset fixture in a language with no wordlist, whose text is valid words, **when** the check runs, **then** no page is rejected.

<a id="ocr-ac8"></a>**OCR-AC8** (covers [OCR-R2](#ocr-r2), [OCR-R4](#ocr-r4)): **Given** a born-digital fixture whose text layer would be trusted, and `mode = "always"`, **when** it converts with the fake engine, **then** every non-blank page is OCR'd and each `ocr` event has `trigger: "forced"`.

<a id="ocr-ac9"></a>**OCR-AC9** (covers [OCR-R3](#ocr-r3)): **Given** the no-ToUnicode must-reject fixture and `mode = "never"`, **when** it converts, **then** the engine is never called, the outcome is `converted`, the rejected pages appear in one `page_fallback` issue (warning) with reason `bad_text_layer`, and the EPUB's text for those pages contains no Private Use Area or U+FFFD characters.

<a id="ocr-ac10"></a>**OCR-AC10** (covers [OCR-R10](#ocr-r10), [OCR-R20](#ocr-r20)): **Given** a rejected prior OCR layer and a fake engine whose every attempt returns coverage and confidence below thresholds, **when** it converts under `auto`, **then** the page falls back with reason `ocr_low_confidence`, the result records 4 attempts, and the page's hidden text is the one (best attempt or original layer) with the lower garbage ratio in the fixture's setup.

<a id="ocr-ac11"></a>**OCR-AC11** (covers [OCR-R11](#ocr-r11), [OCR-R12](#ocr-r12), [OCR-R13](#ocr-r13), [OCR-R15](#ocr-r15)): **Given** real Tesseract (marked `tesseract`) and the clean 300 DPI synthetic page, **when** the adapter recognises it, **then** the result has lines of words with bounding boxes inside the page, every word confidence is in [0, 1] and equals the raw value ÷ 100, `page_confidence` is the length-weighted mean, `attempts` has one entry, and `capabilities()` reports Tesseract's licence as Apache-2.0 and OSD as available.

<a id="ocr-ac12"></a>**OCR-AC12** (covers [OCR-R14](#ocr-r14), [OCR-R22](#ocr-r22)): **Given** a fake `tesseract` program that sleeps forever and `page_timeout = 2`, **when** a page is OCR'd, **then** the subprocess is killed within 2 seconds plus a short grace, no `tesseract` process remains, the page falls back with reason `ocr_timeout`, and an `ocr_timeout` warning lists that page.

<a id="ocr-ac13"></a>**OCR-AC13** (covers [OCR-R14](#ocr-r14)): **Given** a fake `tesseract` program that writes its environment to a file, and `PDF2EPUB_PASSWORD` set in the parent, **when** a page is OCR'd, **then** the recorded environment has `OMP_THREAD_LIMIT=1` and no `PDF2EPUB_PASSWORD`.

<a id="ocr-ac14"></a>**OCR-AC14** (covers [OCR-R23](#ocr-r23)): **Given** a fake `tesseract` program that exits with status 1 on every call, **when** a 2-page scanned fixture converts, **then** the outcome is `converted`, both pages fall back with reason `ocr_failed`, and one `ocr_failed` warning lists pages `[1, 2]`.

<a id="ocr-ac15"></a>**OCR-AC15** (covers [OCR-R16](#ocr-r16), [OCR-R19](#ocr-r19)): **Given** a synthetic page with known ink and a fake engine result that boxes exactly half of the ink with confidence 0.95, **when** the attempt is scored, **then** coverage is 0.5 ± 0.02 and the attempt is not accepted, even though its confidence is above `p_min`.

<a id="ocr-ac16"></a>**OCR-AC16** (covers [OCR-R20](#ocr-r20), [OCR-R21](#ocr-r21)): **Given** a fake engine whose first attempt has low coverage and whose `BLOCK` attempt is acceptable, **when** a page is OCR'd at `balanced`, **then** exactly 2 attempts run and the second is kept; at `fast`, exactly 1 attempt runs and the page falls back with `ocr_low_confidence`; at `best`, all 4 attempts run and the one with the highest (coverage, confidence) is kept.

<a id="ocr-ac17"></a>**OCR-AC17** (covers [OCR-R19](#ocr-r19), [OCR-R27](#ocr-r27)): **Given** a fake engine returning full coverage and confidence 0.80 on every attempt, **when** a page is OCR'd with `min_confidence = 0.75`, **then** the baseline attempt is accepted; **and when** `min_confidence = 0.90`, **then** the page falls back with `ocr_low_confidence`.

<a id="ocr-ac18"></a>**OCR-AC18** (covers [OCR-R18](#ocr-r18)): **Given** the synthetic 2°-skewed, 90°-rotated and 150 DPI page variants and real Tesseract, **when** each is OCR'd at `balanced`, **then** the image passed to the engine is upright, its measured skew is under 0.5°, its DPI is 300 ± 10, and the fallback image (if any) is the un-cleaned render.

<a id="ocr-ac19"></a>**OCR-AC19** (covers [OCR-R24](#ocr-r24)): **Given** a batch of one scanned and one born-digital fixture, and `tesseract_path` pointing to a missing file, **when** the batch runs, **then** the scanned conversion is `converted` with one `ocr_unavailable` warning carrying an install hint and all its pages fall back with reason `ocr_unavailable`; the born-digital conversion has no OCR issue; the exit code is 0; and the missing program was probed exactly once.

<a id="ocr-ac20"></a>**OCR-AC20** (covers [OCR-R24](#ocr-r24)): **Given** real Tesseract and `languages = "xyz"` (no such language data), **when** a scanned fixture converts, **then** it carries `ocr_unavailable` and its pages fall back.

<a id="ocr-ac21"></a>**OCR-AC21** (covers [OCR-R25](#ocr-r25)): **Given** real Tesseract and `engine_options = {"tesseract.not_a_param": "1"}`, **when** a batch is started through the CLI, **then** it exits with code 2, no conversion starts, and no EPUB is written; **and given** `{"tesseract.preserve_interword_spaces": "1"}`, the batch runs.

<a id="ocr-ac22"></a>**OCR-AC22** (covers [OCR-R26](#ocr-r26)): **Given** a scanned fixture whose PDF metadata says `de` and the fake engine, **when** it converts (a) with no language options, (b) with `ConversionOptions.language = "fr"`, (c) with `OcrOptions.languages = "eng+fra"`, and (d) with no metadata language and no options, **then** the request's `languages` is `deu`, `fra`, `eng+fra` and `eng` respectively.

<a id="ocr-ac23"></a>**OCR-AC23** (covers [OCR-R28](#ocr-r28)): **Given** a scanned fixture whose source text had italic words, **when** it converts with real Tesseract, **then** the EPUB contains no `<em>`, `<i>`, `<strong>` or `<b>` elements in text from OCR'd pages.

<a id="ocr-ac24"></a>**OCR-AC24** (covers [OCR-R29](#ocr-r29), [OCR-R30](#ocr-r30)): **Given** a 2-page scanned fixture and the fake engine, **when** it converts, **then** exactly 2 `progress` events with stage `ocr` are emitted, each with numeric `confidence` and `coverage`, integer `attempts` ≥ 1, boolean `fell_back` and a `trigger`; the conversion result has `ocr.engine = "tesseract"`, `ocr.languages` and `ocr.quality = "balanced"`; and a born-digital conversion in the same batch has `ocr: null`. The EPUB's package metadata contains no mention of OCR or Tesseract.

<a id="ocr-ac25"></a>**OCR-AC25** (covers [OCR-R31](#ocr-r31), [OCR-R17](#ocr-r17)): **Given** a fake engine that returns no words for every page, **when** a born-digital fixture with a good typeset text layer is converted with `mode = "always"`, **then** every page keeps its original text and no `page_fallback` issue is raised; **when** the must-reject garbled-layer fixture is converted with `mode = "always"`, **then** each of its pages is a page image with `page_fallback` reason `ocr_low_confidence` and no hidden text; **and when** a blank scanned page with no text layer is converted, **then** no issue is raised.

## Open points

- The exact fraction for "almost no text" and "an image covering a large share of the page" in [OCR-R1](#ocr-r1) is left as an internal constant, set while building the routing slice.
- [OCR-R9](#ocr-r9): when several signals fail on one page, the reason reported is the first in the order garbled → implausible_words → low_coverage (assumed; one reason per page keeps grouping simple).
- [OCR-R20](#ocr-r20): the ladder's step 3 runs whenever confidence is below `p_min` after step 2 (or after step 1 if step 2 was skipped). The decision text listed "Sauvola, then denoise"; read here as Sauvola alone, then Sauvola plus denoise.
- [OCR-R22](#ocr-r22)/[OCR-R23](#ocr-r23): a timed-out or failed page is listed both in `page_fallback` (reason `ocr_timeout`/`ocr_failed`) and in the `ocr_timeout`/`ocr_failed` diagnostic issue, per the shared grouping rule in [api](api.md).
- [OCR-R26](#ocr-r26): the mapping from BCP 47 tags (e.g. `de`) to Tesseract codes (e.g. `deu`) is a built-in table; an unmappable language falls back to `eng`.
- [OCR-AC10](#ocr-ac10) counts 4 attempts, assuming the fake engine's failures trigger every ladder step.
