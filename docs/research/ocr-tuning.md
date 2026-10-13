# OCR engine tuning surface

Research for [#12](https://github.com/Bezoar/pdf2epub/issues/12), feeding the
engine-interface design in [#13](https://github.com/Bezoar/pdf2epub/issues/13).
Date: 2026-10-13. Scope: single-column scanned print books, Tesseract first,
other engines behind the same interface later.

Each claim is cited. **[local]** marks a result from the small experiment in
[Appendix A](#appendix-a-local-experiment). It was run on this machine with
Tesseract 5.5.0, Leptonica 1.85.0 and Homebrew's `eng.traineddata` (4.1 MB,
which is the size of a tessdata_fast model). It is **one synthetic page**, so
treat it as a sanity check, not a benchmark.

---

## 1. Key findings

1. **Line geometry matters most.** Skew, orientation, and whether the image
   matches the engine's layout assumption have the biggest effect. [local] At 3° of
   skew, Tesseract's default `--psm 3` dropped 58% of the words. At 6° it
   dropped 97%. Deskewing first brought both back to 0% error. Tesseract's own
   guide says skew "degrades line segmentation" ([tessdoc ImproveQuality][iq]).
2. **Glyph size matters next.** Tesseract works best at ≥300 DPI
   ([iq]). A large forum test found error rate tracks capital-letter height in
   pixels, with an optimum, more than DPI or point size ([Willus test][willus]).
   [local] At 75 DPI the WER was 13.4%. Upscaling the same image to 300 DPI cut it to 0.9%.
3. **Binarisation helps uneven pages, but no method wins everywhere.**
   [local] On a page with an illumination gradient, blur and noise, Sauvola
   (`thresholding_method=2`) gave 0% CER against 0.75% for Otsu. Adaptive Otsu was
   *worse* (8.1% CER) on the same page at 150 DPI. This supports
   recognition-driven selection: try more than one setting and keep the best,
   as in [Rangoni et al.][rdt] and [Lund et al.][lund].
4. **A high mean confidence does not mean a page is good.** [local] Words that
   Tesseract *did* return on the 3°-skew page averaged 95% confidence, even though
   58% of the page's words were missing. Engine confidence covers only the text
   the engine found, not the text it missed. The interface needs a **coverage**
   signal as well as confidence (§9.3).
5. **Word confidence is still a useful filter.** [local] Pooled over the
   degraded pages, words at ≥93 were 99% correct. Words at 50–93 were
   about 80% correct, and words below 50 were 62% correct.
6. **tessdata_best is not a free win.** It was about 2× slower than fast. Accuracy was
   mixed: slightly better on the noisy page, worse at 75 DPI and on skewed pages
   ([local]; the [Data-Files docs][datafiles] say "Most users will want
   tessdata_fast"). Model choice should be a preset, not a default switch.
7. **Engines are broadly alike, but licences differ.** All the open
   engines surveyed have Apache-2.0 or MIT **code**. **Weights** differ: Surya's
   weights use a modified OpenRAIL-M licence with a revenue cap, which makes them
   unsuitable as a bundled default. Apple Vision is an OS API, macOS only. See §2.
8. **OCRmyPDF is a close precedent.** It already has a plugin
   `OcrEngine` ABC, per-page timeouts that fall back to the page image, and
   rotation applied above a confidence threshold. pdf2epub's interface can borrow its
   shape ([pluginspec.py][omp-spec]).

---

## 2. Engines and licences (MIT-compatibility)

"Code" and "weights" are licensed separately. Apache-2.0 and MIT are both
compatible with an MIT project that *depends on* them. Apache-2.0 requires
NOTICE preservation if redistributed.

| Engine | Code licence | Model/weights licence | MIT-compatible? | Notes |
|---|---|---|---|---|
| Tesseract 5.x | Apache-2.0 ([LICENSE][tess-lic]) | tessdata_best / tessdata_fast: Apache-2.0 ([tessdata_best README][tdbest]; `gh api repos/tesseract-ocr/tessdata_fast` → Apache-2.0) | Yes | C++ CLI/library. Python bindings: pytesseract (Apache-2.0, CLI wrapper), tesserocr (MIT, C-API binding), both checked via `gh api repos/.../license`. |
| OCRmyPDF (reference, not an engine) | MPL-2.0 ([LICENSE][omp-lic]) | n/a | Usable as a dependency (file-level copyleft). Don't copy its code into MIT files. | Depends on Ghostscript (AGPLv3) unless pypdfium2 is used ([intro][omp-intro], [cli.py][omp-cli]). |
| unpaper (preprocessor) | GPL-2.0 ([README][unpaper]) | n/a | Only as an external subprocess, never linked or vendored | |
| ScanTailor Advanced (preprocessor) | GPL-3.0 ([repo][sta]) | n/a | External tool only. Last push 2023-09 (`gh api`). | GUI-oriented |
| PaddleOCR (PP-OCRv5/v6) | Apache-2.0 (`gh api repos/PaddlePaddle/PaddleOCR`) | Apache-2.0 on HF model cards (e.g. [PP-OCRv5_server_rec][pp-hf]) | Yes | Heavy PaddlePaddle runtime |
| RapidOCR | Apache-2.0 ([README][rapid]) | PaddleOCR models converted to ONNX ([README][rapid]) → Apache-2.0 | Yes | Light ONNX Runtime/OpenVINO; good "second engine" candidate |
| docTR | Apache-2.0 (`gh api repos/mindee/doctr`) | Apache-2.0 on HF (e.g. [doctr parseq multilingual][doctr-hf]) | Yes | PyTorch |
| EasyOCR | Apache-2.0 ([README][easy]) | Detector = CRAFT pretrained weights from clovaai ([README][easy]). CRAFT-pytorch repo is MIT (`gh api repos/clovaai/CRAFT-pytorch`). Recognizer weights come from JaidedAI's model hub with no separate licence stated. | Probably. Confirm recognizer weight terms before bundling. | |
| Surya 2 | Apache-2.0 ([README][surya]) | "modified AI Pubs Open Rail-M … free for research, personal use, and startups under $5M funding/revenue" ([README][surya]); HF tag `license:openrail` ([HF][surya-hf]) | Code yes. **Weights are not OSI-open.** Users may opt in; don't make it a default. | VLM via vllm/llama.cpp server |
| Apple Vision (`VNRecognizeTextRequest`, `RecognizeDocumentsRequest`) | Proprietary OS framework | Ships with OS (macOS 10.15+ for `VNRecognizeTextRequest`; macOS 26 for `RecognizeDocumentsRequest`) ([docs][av-req], [docs][av-docreq]) | Yes to *call* (nothing is redistributed), but macOS/iOS only | Needs a Swift/PyObjC bridge |
| Kraken (not surveyed in depth) | Apache-2.0 (`gh api`) | — | Yes | Historical-document focus |
| Calamari (not surveyed) | GPL-3.0 (`gh api`) | — | No (not as a linked dependency) | |

---

## 3. Input / rendering knobs

| Knob | What it does | Engines | Evidence for scanned books | Exposure |
|---|---|---|---|---|
| **Render / target resolution** | DPI at which the PDF page is rasterised, or to which an embedded scan is resampled | All, through the image itself. Tesseract also reads `--dpi` / `user_defined_dpi` ([`--print-parameters`][local-params]; [man page][man]). | Tesseract: "works best on images which have a DPI of at least 300" ([iq]). Error rate tracks capital-letter height in px, and there is an optimum: very large glyphs also cause errors ([Willus][willus]). OCRmyPDF `--oversample` "to improve OCR results slightly" ([cli.py][omp-cli]). Surya suggests lowering DPI from 192 to 96 for throughput and capping width at about 2048 px ([README][surya]). [local] 75 DPI: WER 13.4% → 0.9% after upscaling to 300. 100 DPI: WER 1.7% → 0%. | **Auto.** Target a glyph height, not a DPI: measure x-height and rescale. Users get `--ocr-dpi` as an override only. |
| **Declared DPI** | Tells the engine the resolution, which affects size-based heuristics (e.g. Sauvola window is "multiplied by image DPI") | Tesseract (`--dpi`, `user_defined_dpi`; `thresholding_window_size` "to be multiplied by image DPI") ([local-params]) | Without it, Tesseract reads DPI from image metadata ([man]). Wrong metadata skews the thresholding window. | **Internal.** Always pass the real DPI. |
| **Rasteriser / anti-aliasing** | Which renderer produces the page image | Pipeline-level | OCRmyPDF: Ghostscript 10.x "can render aliased glyphs that OCR misreads as extra word breaks". pypdfium2 "generally produces better input for OCR" ([cli.py][omp-cli]). | **Internal** (choose the anti-aliased renderer). For image-only pages, prefer extracting the embedded image at native resolution over re-rendering. |
| **Colour mode** | Feed colour, grey or bilevel | All. Tesseract binarises internally. DL engines want RGB or grey. | Tesseract 4.x+ blends alpha onto white, which "can fail in some cases" ([iq]). | **Internal.** Grey for Tesseract, RGB for DL engines. Strip alpha. |
| **Max image size** | Limit on pixels sent to OCR | Tesseract hard limit 32767 px per dimension ([OCRmyPDF advanced][omp-adv]). RapidOCR `max_side_len` 2000 ([RapidOCR params][rapid-params]). EasyOCR `canvas_size` 2560 ([EasyOCR docs][easy-doc]). PaddleOCR `text_det_limit_side_len`/`_type` ([Paddle OCR pipeline][pp-doc]). | OCRmyPDF downsamples above the limit, noting it "may reduce OCR quality" ([tesseract_ocr.py][omp-tess-plugin]). Peak memory is about jobs × 16 B × megapixels ([cli.py][omp-cli]). | **Internal** guard plus resource preset |
| **Region of interest / crop** | OCR only part of the page | Tesseract `SetRectangle` ([baseapi.h][baseapi]). Vision `regionOfInterest` ([docs][av-req]). | Large empty borders can yield "empty page"; text cropped too tightly needs about 10 px of white border ([iq]). | **Internal** (used by retries and by the border-removal step) |
| **Two-up spread split** | Split a scan of two facing pages | unpaper `--layout double` ([OCRmyPDF advanced][omp-adv]). ScanTailor "Split Pages" ([repo][sta]). | Needed for books scanned open-flat. Otherwise the page is two columns and the reading order breaks. | **Auto-detect** (aspect ratio plus a gutter projection), with a user override `--split-spreads` |

## 4. Preprocessing knobs

| Knob | What it does | Engines / tools | Evidence | Exposure |
|---|---|---|---|---|
| **Orientation (0/90/180/270)** | Detect and fix cardinal rotation | Tesseract OSD (`--psm 0`, or 1/12 inline; needs `osd.traineddata`) → "Orientation in degrees / Orientation confidence / Script" ([local] output). OCRmyPDF `--rotate-pages` applies it only if confidence ≥ `--rotate-pages-threshold` (default **14**) ([_defaults.py][omp-defaults], [cli.py][omp-cli]). PaddleOCR `use_doc_orientation_classify` (PP-LCNet doc_ori, 99.06% top-1) ([pp-doc]). docTR `detect_orientation`/`straighten_pages` ([doctr-doc]). EasyOCR `rotation_info` ([easy-doc]). | Lower thresholds "rotate more often but produce more false positives" ([cookbook][omp-cook]). [local] A 90° page gave OSD conf 26.45 (rotation correctly detected), and `--psm 3` alone also read it correctly. | **Auto**, with a confidence threshold as a preset. Log weak detections ("OSD: Weak margin" → OCRmyPDF warns "unsure about page orientation", [_exec/tesseract.py][omp-exec]). |
| **Deskew (small angles)** | Rotate so lines are horizontal | Tesseract reports "Deskew angle" under `--psm 2`, which is how OCRmyPDF `--deskew` gets its angle ([_exec/tesseract.py][omp-exec]). unpaper deskew (scan range default 5°) ([unpaper image-processing][unpaper-ip]). ScanTailor Deskew ([sta]). docTR `assume_straight_pages=False` ([doctr-doc]). | "Heavily skewed" pages degrade line segmentation ([iq]). [local] Skew 1°: CER 0.08%. Skew 3°: CER 57%. Skew 6°: CER 96%. After deskew: 0% in all cases. `--psm 6` (single block) mostly survived skew (3°: CER 0.4%; 6°: CER 3.8%). | **Auto, always on** for OCR'd pages. Cheap, and the biggest win measured. |
| **Binarisation** | Grey → black/white | Tesseract internal `thresholding_method` 0=Otsu, 1=Leptonica adaptive Otsu, 2=Sauvola (5.0+), with `thresholding_window_size`, `_kfactor`, `_tile_size`, `_smooth_kernel_size`, `_score_fraction` ([local-params]; [ReleaseNotes][rel]). OCRmyPDF `--tesseract-thresholding auto/otsu/adaptive-otsu/sauvola` ([tesseract_ocr.py][omp-tess-plugin]). ScanTailor Sauvola/Wolf ([sta]). DL engines take grey/RGB and don't binarise. | Uneven backgrounds defeat global Otsu ([iq]). Original adaptive method: [Sauvola & Pietikäinen 2000][sauvola]. Choosing the threshold from OCR output reduced the words-not-in-dictionary error rate by 6% on 740 Google Books pages ([Rangoni et al.][rdt]). Combining OCR of several thresholds cut a lattice WER from ≥13.8% to 7.6% on 19th-century newspapers ([Lund et al.][lund]). [local] On a dirty page: Otsu 0.75% CER, Sauvola 0%, adaptive Otsu 0.17%. At 150 DPI: adaptive Otsu **8.1%**, Otsu and Sauvola 0%. | **Preset plus auto-retry.** Start with Otsu, and retry with Sauvola on low-confidence or low-coverage pages. Not a first-class user option. Expose only through engine passthrough. |
| **Denoise / despeckle** | Remove specks and salt-and-pepper noise | unpaper noisefilter, blurfilter, grayfilter, blackfilter ([unpaper-ip]). ScanTailor despeckle 1.0/2.0/3.0 ([sta]). Tesseract `enable_noise_removal` (on), `textord_heavy_nr` ([local-params]). | Noise is "read as text" ([cookbook][omp-cook]). Cloud engines beat Tesseract "especially on noisy documents" ([Hegghammer 2022][hegg]). OCRmyPDF's default unpaper args *disable* grayfilter, blackfilter and deskew to avoid deleting content ([_exec/unpaper.py][omp-unpaper]). `--clean-final` "might remove desired content" ([cli.py][omp-cli]). | **Preset** (off / light / aggressive). Only send the cleaned image to OCR, never into the EPUB fallback image. |
| **Background / illumination normalisation** | Flatten shading, yellowing and show-through | OCRmyPDF `--remove-background` (currently "temporarily not implemented" for non-mono pages, [_pipeline.py][omp-pipe]). ScanTailor illumination normalisation ([sta]). | Same mechanism as binarisation: adaptive thresholds exist because of uneven illumination ([iq]). | **Preset** (part of the "degraded scan" profile) |
| **Border / scanner-edge removal** | Remove dark scan margins, gutter shadow and thumbs | unpaper mask/border detection ([unpaper basic concepts][unpaper-bc]). ScanTailor Select Content / Margins ([sta]). | Dark borders get "misread as characters"; big borders can produce empty-page results ([iq]). | **Auto** (crop to the content mask, pad 10–20 px) |
| **Upscaling** | Interpolate small glyphs up | Pipeline-level | See resolution, §3. [local] Lanczos upscaling from 75/100 → 300 DPI recovered nearly all accuracy. | **Auto**, driven by measured x-height |
| **Dilation / erosion** | Thicken thin or broken strokes, thin bold or bled ones | Pipeline-level | Recommended for bold or ink-bled text ([iq]). No quantitative evidence found. | **Retry strategy only** |
| **Dewarping** | Flatten page curvature near the spine | PaddleOCR `use_doc_unwarping` (UVDoc model, CER 0.179 on DocUNet) ([pp-doc]). ScanTailor auto/manual/marginal dewarping ([sta]). Tesseract has none. | UVDoc paper: OCR CER gains on its own benchmark, roughly flat on DocUNet ([UVDoc][uvdoc]). Matters for camera or book-scanner captures, much less for flatbed or sheet-fed scans. | **Off by default. User opt-in** (`--dewarp`). Out of v1 scope for Tesseract-only. |
| **Inversion (light-on-dark)** | Retry inverted lines | Tesseract `invert_threshold` (default 0.7; 0 disables; `tessedit_do_invert` deprecated in 5.2) ([rel]; [local-params]). | Tesseract 4.x+ expects dark-on-light text ([iq]). | **Internal default.** Consider `invert_threshold=0` for speed on plain book pages (an unmeasured win). |

## 5. Recognition knobs

| Knob | What it does | Engines | Evidence | Exposure |
|---|---|---|---|---|
| **Engine** | Which OCR backend | — | Hegghammer: server engines beat Tesseract on noisy scans ([hegg]). Surya 2 scores only 41.8 on olmOCR-bench "OldScan" against 99.7 on "Base" ([Surya README][surya]). Old scans are hard for every engine. | **User** (`--ocr-engine`), default `tesseract` |
| **Model variant** | Size/accuracy trade-off | Tesseract `tessdata` (legacy + LSTM), `tessdata_best` (slowest, most accurate, retrainable), `tessdata_fast` (fastest, least accurate) ([datafiles]). PaddleOCR mobile/server, `ocr_version` ([pp-doc]). RapidOCR `model_type` ([rapid-params]). docTR `det_arch`/`reco_arch` ([doctr-doc]). EasyOCR `recog_network` ([easy-doc]). Vision `recognitionLevel` fast/accurate, `revision` ([av-level]). | [local] tessdata_best was about 2× slower than fast, and was no better on 5 of 6 pages (e.g. 75 DPI WER 13.4% → 17.7%; noisy page 1.72% → 1.29%). PaddleOCR v5 server vs mobile rec: 86.38 vs 81.29 on Chinese, but 64.70 vs **66.00** on English ([pp-doc]). | **Preset** (`fast`/`balanced`/`best`), mapped per engine |
| **Engine mode** | Tesseract legacy vs LSTM vs both | `--oem 0/1/2/3` ([local-params]). Legacy needs `tessdata`, not best/fast ([datafiles]). | Legacy is needed only for OSD (osd.traineddata) and some legacy-only features. | **Internal** (LSTM, `--oem 1`) |
| **Language / script** | Choose the model(s) and dictionary | Tesseract `-l eng+deu`, `script/Latin` ("a script also supports English") ([man]). Vision `recognitionLanguages`, `automaticallyDetectsLanguage` ([av-req]). PaddleOCR/RapidOCR `lang`. EasyOCR `lang_list`. Surya auto. | Language order changes Tesseract's time and output ([CLI usage][cliuse]). OSD returns the script with a confidence ([local]). | **User** (`--lang`, already in the SPEC). Auto-detect from PDF metadata or OSD script when unset. |
| **Page segmentation / layout assumption** | How the page is split into blocks and lines | Tesseract `--psm 0–13` ([local-params]). Default 3 on the CLI, but the raw parameter default is **6** in `--print-parameters` (relevant if using the C API via tesserocr) ([local-params]). docTR `resolve_lines`/`resolve_blocks`/`paragraph_break` ([doctr-doc]). EasyOCR `paragraph` and merge thresholds ([easy-doc]). | OCRmyPDF: "For the vast majority of users, changing the page segmentation mode will only make things worse" ([omp-adv]). [local] `--psm 6` hurt on a noisy page (CER 3.25% vs 0.75%) but rescued skewed pages. `--psm 4` (single column) behaved like 3. | **Internal.** psm 3 by default, psm 6 as a *retry* when coverage is low. Never user-facing except through passthrough. |
| **Dictionary / language model** | Penalise non-dictionary words | Tesseract `load_system_dawg`, `load_freq_dawg`, `language_model_penalty_non_dict_word` (0.15), `…_non_freq_dict_word` (0.1) ([local-params]). Vision `usesLanguageCorrection` ([av-req]). | Turn off for non-word text such as part numbers ([iq]; [omp-adv] warns it "may interfere with OCR if the document does not contain many words"). [local] On book prose, turning it off made no difference. | **Internal on.** Off only through passthrough. |
| **User words / patterns / custom lexicon** | Boost domain vocabulary (character names, places) | Tesseract `--user-words`, `--user-patterns` ([man]). Vision `customWords` ("take precedence over the standard lexicon"; ignored if `usesLanguageCorrection` is false) ([av-cw]). | Tessdoc recommends them for known input ([iq]). Effectiveness with LSTM is weakly documented. | **User (advanced)** `--ocr-words FILE`. Potential **auto**: harvest high-confidence proper nouns from the book's first pass. |
| **Character allow/deny list** | Restrict the output alphabet | Tesseract `tessedit_char_whitelist`/`_blacklist`/`_unblacklist` (LSTM support since 4.1.0) ([rel]). EasyOCR `allowlist`/`blocklist` ([easy-doc]). docTR `add_whitelist` ([doctr-doc]). | Useful for digit-only regions ([iq]). Harmful for prose. | **Internal** (e.g. page-number re-OCR with digits and roman numerals) |
| **Detection thresholds** | When a pixel blob counts as text | PaddleOCR `text_det_thresh` 0.3, `text_det_box_thresh` 0.6, `text_det_unclip_ratio` 2.0 ([pp-doc]). RapidOCR `thresh` 0.3, `box_thresh` 0.5, `unclip_ratio` 1.6 ([rapid-params]). EasyOCR `text_threshold` 0.7, `low_text` 0.4, `link_threshold` 0.4, `min_size` 10 ([easy-doc]). docTR `bin_thresh`, `box_thresh` ([doctr-doc]). Surya `DETECTOR_TEXT_THRESHOLD`/`_BLANK_THRESHOLD` ([surya]). Vision `minimumTextHeight` (default 1/32 of image height) ([av-mth]). | Surya: lower the thresholds if faint text is missed, raise them if lines merge ([surya]). Vision: raising `minimumTextHeight` saves memory but ignores small text ([av-mth]). Footnotes in books are small, so the Vision default matters. | **Engine-specific passthrough.** The adapter sets book-appropriate defaults (e.g. Vision `minimumTextHeight` ≈ 0.01). |
| **Text-line orientation (180° per line)** | Classify upside-down lines | PaddleOCR `use_textline_orientation` ([pp-doc]). RapidOCR `use_cls` ([rapid-params]). docTR crop orientation ([doctr-doc]). | Rare in books once the page orientation is fixed | **Internal off** (after page OSD) |
| **Decoder** | Greedy vs beam search | EasyOCR `decoder`, `beamWidth` ([easy-doc]). Tesseract `lstm_choice_mode`/`lstm_choice_iterations` affect alternatives output ([local-params]). | No book-specific evidence found | **Passthrough** |
| **Recognition score cut-off** | Drop low-score lines in the engine | PaddleOCR `text_rec_score_thresh` (default 0.0) ([pp-doc]). RapidOCR `text_score` 0.5 ([rapid-params]). | Silently dropping text hides problems | **Internal: force 0** (keep everything and decide in pdf2epub using confidence) |
| **Whitespace preservation** | Keep runs of spaces | Tesseract `preserve_interword_spaces` ([local-params]; [cliuse]) | Irrelevant for reflowable prose | **Internal off** |

## 6. Post-processing knobs (pdf2epub side, engine-agnostic)

| Knob | What it does | Evidence | Exposure |
|---|---|---|---|
| **Unicode/ligature normalisation** | NFC, ﬁ→fi, curly quotes | Already in SPEC §5.2 for text PDFs. OCR output needs the same. | Internal |
| **De-hyphenation across line ends** | Join `pos-\nsession` | Standard post-OCR step ([Nguyen et al. 2021 survey][survey]) | Internal (shared with text path) |
| **Dictionary/statistical correction** | Fix likely errors against a lexicon | Survey of methods: [Nguyen et al., ACM CSUR 2021][survey]. Aligning repeat scans of the same book corrects "over six times as many errors as it introduces" ([Kim et al., EMNLP Findings 2021][dirty]). | Opt-in preset; v2 |
| **Multi-pass voting** | OCR several variants (thresholds, engines), then align and vote | [Lund et al.][lund] (lattice WER 13.8% → 7.6%). [Rangoni et al.][rdt]. | **Auto, but only in the low-confidence retry path** (cost ×N) |
| **LLM correction** | Rewrite text with an LLM | GPT-4-class: mean CER improvement 18.9% (38.8% with a quality-estimation gate), but "overcorrect texts whose OCR quality is already good" ([Zhang et al., DocEng 2024][ppa]). Open-weight LLMs helped English but not Finnish ([Kanerva et al. 2025][nofree]). | **Out of scope for v1.** If added later, gate it on low confidence and keep the original text. |
| **Confidence-based page fallback** | Replace a page with its image when quality is low | SPEC v1 decision. OCRmyPDF inserts the page "without OCR" on timeout ([omp-adv]). | Threshold as a **preset** (`--ocr-min-confidence`), with an advanced user override |
| **Running header/footer and page-number removal** | Remove repeated furniture | SPEC §5.4.3 already does this. OCR output feeds the same span model. | Existing |

## 7. Output / confidence granularity

| Engine | Levels with geometry | Confidence granularity and scale | Alternatives | Other useful output |
|---|---|---|---|---|
| Tesseract | page, block, para, line, word, symbol (`RIL_BLOCK…RIL_SYMBOL`, [publictypes.h][pubtypes]) | Word 0–100 (`AllWordConfidences`, `MeanTextConf` [baseapi.h][baseapi]). TSV `conf` is −1 on non-word rows ([local]). hOCR `x_wconf` per word, `x_conf` per char with `hocr_char_boxes=1`. ALTO `WC` 0–1. | `lstm_choice_mode=1/2` adds per-character alternatives to hOCR ([local-params]; [rel]) | Line `baseline`, `x_size`, ascender/descender heights in hOCR. `x_fsize` with `hocr_font_info=1`, but **no bold/italic from LSTM** ([local]: no `x_font` emitted). Formats: txt, hOCR, TSV, ALTO, PAGE, PDF ([man]). |
| Apple Vision | Observation (line) with box, plus `boundingBox(for:)` sub-ranges | 0.0–1.0 per candidate ([av-conf]) | `topCandidates(n)` ([av-top]) | macOS 26 `RecognizeDocumentsRequest` groups words, lines, paragraphs, tables and lists ([av-docreq]) |
| PaddleOCR | line polygon/box. Word boxes via `return_word_box` ([pp-doc]) | `rec_scores` per line, detection `dt_scores` ([pp-doc]) | — | doc orientation and unwarp results |
| RapidOCR | line box. Word/char boxes via `return_word_box`/`return_single_char_box` ([rapid-params]) | per line | — | |
| docTR | page → block → line → word ([doctr-doc]) | word `confidence`, `objectness_score` ([doctr-doc]) | — | page orientation and language. hOCR-style XML export with `x_wconf` ([doctr-doc]). |
| EasyOCR | word/phrase box, or paragraph (`paragraph=True`) ([easy-doc]) | per box (`detail=1`) | — | |
| Surya 2 | block (polygon, bbox, layout label, reading order) ([surya]) | block = "mean per-token probability" 0–1 ([surya]) | — | layout labels (PageHeader, SectionHeader…), HTML with inline math |

**Common denominator:** a **line** with a box (or polygon) and a confidence in
[0, 1], containing text. Every engine provides this or can derive it. Word
boxes are available from all except Surya (block-level) and Vision (line plus
sub-range boxes). Character level, alternatives, font size and baseline are
engine-specific extras. Confidence scales differ (0–100, 0–1, token
probability) and are **not calibrated across engines**. Treat them as
engine-relative and calibrate per engine.

## 8. Resource-limit knobs

| Knob | Engines | Evidence | Exposure |
|---|---|---|---|
| **Per-page timeout** | Tesseract CLI has **no** timeout flag ([local] `--help-extra`). The C++ API has `ETEXT_DESC::set_deadline_msecs` plus a `cancel` callback ([ocrclass.h][ocrclass]), and `ProcessPages(…, timeout_millisec, …)` ([baseapi.h][baseapi]). Note: "Progress monitor covers word recognition and it does not cover layout analysis" ([ocrclass.h][ocrclass]), so a deadline cannot interrupt a stuck layout phase. OCRmyPDF uses subprocess `timeout=` (default 180 s OCR, 180 s non-OCR for OSD/deskew) ([tesseract_ocr.py][omp-tess-plugin]). | A timed-out page is "inserted without OCR" ([omp-adv]). | **Preset** (default ~60–180 s/page, scaled by megapixels). User override `--ocr-timeout`. Enforce by **killing a subprocess or worker**, not only the API deadline. |
| **Threads per page** | Tesseract OpenMP: "uses up to four CPU threads" per page. `OMP_THREAD_LIMIT=1` disables it ([FAQ][faq]). OCRmyPDF sets it when parallelising pages ([omp-adv]). PaddleOCR `cpu_threads` 10, `enable_mkldnn` ([pp-doc]). RapidOCR ONNX `intra_op_num_threads` ([rapid-params]). | "four threads on a two-core machine" slows things down ([faq]). Engines "should not introduce more parallelism" under OCRmyPDF's page-parallel model ([omp-spec]). | **Internal.** Pin engine threads to 1 and parallelise pages (SPEC already uses a process pool). |
| **Concurrency / batch size** | docTR `det_bs` 2, `reco_bs` 128 ([doctr-doc]). EasyOCR `batch_size`, `workers` ([easy-doc]). RapidOCR `rec_batch_num` ("too large: no clear speed-up, results may be worse") ([rapid-params]). Surya `SURYA_INFERENCE_PARALLEL` 8, `DETECTOR_BATCH_SIZE` ([surya]). | — | Engine-specific passthrough plus a `--jobs` user knob |
| **Memory / image cap** | OCRmyPDF `--max-ocr-image-mpixels`, `--skip-big` ([cli.py][omp-cli]; [omp-adv]). Vision `preferBackgroundProcessing` lowers the memory footprint at a time cost ([av-bg]). | Peak memory about jobs × 16 B × MP ([omp-cli]) | **Internal guard.** Optional `--ocr-max-megapixels`. |
| **Device / precision** | PaddleOCR `device`, `precision` fp32/fp16, `use_tensorrt` ([pp-doc]). EasyOCR `gpu`, `quantize` ([easy-doc]). Vision `usesCPUOnly` (deprecated macOS 14) ([av-cpu]). Surya backend vllm/llama.cpp ([surya]). | — | Passthrough, with an auto default |
| **Model load amortisation** | EasyOCR `Reader` "needs to run only once" ([easy]). Surya `--keep_server` ([surya]). Tesseract `Init` per process. | Startup can dominate per-page time | **Internal.** Keep one engine instance per worker process. |

---

## 9. Implications for an engine-agnostic interface (input to #13)

### 9.1 Request

```text
OcrRequest
  image            grey/RGB raster, already preprocessed (pipeline owns preprocessing)
  dpi              true resolution after any rescale
  languages        ordered list of BCP-47/ISO 639 codes (adapter maps to eng/deu, en-US, ...)
  layout_hint      PAGE_SINGLE_COLUMN | BLOCK | LINE | WORD | SPARSE   (abstract PSM)
  region           optional crop rect
  lexicon          optional user words (adapter maps to --user-words / customWords / ignore)
  charset          optional allow-list (adapter maps or reports unsupported)
  want             {granularity: LINE|WORD|CHAR, alternatives: bool, layout_labels: bool}
  deadline         wall-clock budget for this call
```

Preprocessing (orientation, deskew, crop, rescale, binarise, denoise) should
live in **pdf2epub**, not in engines. Reasons: (a) it is engine-agnostic.
(b) The retry ladder needs to vary it. (c) The fallback page image must be
the *un*-cleaned image (OCRmyPDF keeps "clean" and "clean-final" separate,
[cli.py][omp-cli]). Engines may *also* offer internal preprocessing
(Tesseract thresholding, Paddle unwarp/orientation). Expose those as engine
options, defaulted off where the pipeline already does the job.

### 9.2 Options model: three layers

1. **Universal options** (typed, validated, mapped by every adapter):
   `languages`, `quality_preset` (`fast`/`balanced`/`best`), `layout_hint`,
   `timeout`, `threads`, `lexicon`.
2. **Capabilities** declared by each engine adapter, such as `supports_osd`,
   `supports_deskew_angle`, `granularities`, `confidence_scale`,
   `supports_alternatives`, `supports_lexicon`, `supports_charset`,
   `max_image_side`, `platforms`, `licence (code, weights)`. The pipeline
   queries these instead of assuming them. This mirrors OCRmyPDF's optional
   `get_deskew` and `supports_generate_ocr()` ([pluginspec.py][omp-spec]).
3. **Engine-specific passthrough**: an opaque `dict[str, str]` namespaced
   by engine (`tesseract.thresholding_method=2`, `paddle.text_det_box_thresh=0.5`).
   It is validated by the adapter, e.g. by checking names against `tesseract
   --print-parameters`. OCRmyPDF escalates "parameter not found" to a hard
   config error ([_exec/tesseract.py][omp-exec]); do the same, because
   "some combinations of control parameters will break Tesseract" ([omp-adv]).
   On the CLI: `--ocr-engine-opt KEY=VALUE` (repeatable), plus
   `--ocr-config FILE`.

**Proposed exposure:**

| User CLI | Preset (named profiles) | Auto / internal |
|---|---|---|
| `--ocr {auto,always,never}` (exists), `--lang`, `--ocr-engine`, `--ocr-quality {fast,balanced,best}`, `--ocr-timeout`, `--jobs`, `--ocr-words FILE`, `--split-spreads`, `--dewarp`, `--ocr-min-confidence`, `--ocr-engine-opt K=V` (advanced) | `scan-clean` (default), `scan-degraded` (Sauvola, denoise, background flatten), `photo` (dewarp, illumination) | render/rescale target, alpha strip, OSD threshold, deskew, border crop, PSM, dictionary on, inversion, thread pinning, score cut-off = 0, retry ladder |

### 9.3 Result model

```text
OcrPageResult
  engine, engine_version, model_id, options_digest   (reproducibility)
  orientation_applied (deg), skew_applied (deg), dpi_used
  lines: [ {bbox|polygon (page coords, top-left origin), baseline?, x_height?,
            confidence ∈ [0,1] (engine-native value kept too),
            words: [ {text, bbox, confidence, alternatives?, chars?} ]?,
            layout_label?} ]
  page_confidence           word-count-weighted mean (calibrated per engine)
  coverage                  fraction of foreground ink inside recognised word boxes
  warnings: [WEAK_ORIENTATION, MANY_DIACRITICS, IMAGE_DOWNSAMPLED, ...]
  attempts: [ {variant, page_confidence, coverage, duration} ]
```

* Normalise **coordinates**: Vision boxes are normalised with a lower-left origin
  ([av-req]); Tesseract uses pixels with a top-left origin.
* Normalise **confidence** to [0, 1], *and* keep the raw value. Don't compare
  across engines without calibration.
* **Coverage** is required because of the [local] skew result: dropped text
  scored 95% mean confidence. Compute it in pdf2epub as ink pixels inside
  word boxes ÷ total ink pixels after border removal. It is engine-agnostic.
* Surface engine diagnostics as warnings. Tesseract's "diacritics" message
  means "possibly poor OCR", and "OSD: Weak margin" means unsure orientation
  ([_exec/tesseract.py][omp-exec]).

### 9.4 Auto-tuning / retry ladder (per page, bounded by the deadline)

1. Baseline: OSD → deskew → border crop → rescale to target glyph height →
   OCR (psm 3, Otsu).
2. If `coverage < c_min` → retry with `layout_hint=BLOCK` (psm 6). [local]
   This rescued skewed pages.
3. If `page_confidence < p_min` → retry with Sauvola, then with denoise.
   Keep the best result by (coverage, confidence) ([Rangoni][rdt]).
4. Optional: vote across attempts ([Lund][lund]), or use a second engine if
   configured.
5. Still below threshold → **page-image fallback** (SPEC decision) and a
   batch issue that records the attempts.

Thresholds are presets, to be calibrated on the corpus chosen in the
test-corpora research. The [local] calibration suggests ≈0.93 word confidence as
a "trusted" boundary for Tesseract fast/eng.

### 9.5 Error semantics

| Condition | Source | Semantics |
|---|---|---|
| Engine not installed / language pack missing | Tesseract `--list-langs`; OCRmyPDF `get_languages` ([_exec/tesseract.py][omp-exec]) | `EngineUnavailable` / `LanguageUnavailable`: fail fast at startup, before any page work. Clear install hint (SPEC §Install). |
| Bad passthrough option | "parameter not found" ([omp-exec]) | `ConfigError`: fail fast, not per page |
| Timeout | subprocess timeout / deadline ([ocrclass]) | `PageTimeout`: page-image fallback plus a batch issue. Non-fatal. |
| Empty page | Tesseract "Empty page!!" or exit 1 with empty output (version-dependent) ([omp-exec]) | `EmptyResult`: not an error. Treat as a blank or illustration page. |
| Image too large | "Image too large" ([omp-exec]) | Downsample and retry once, then `PageFailed` |
| Crash / OOM / non-zero exit | OCRmyPDF tests simulate crash and OOM-killer ([test plugins list][omp-tree]) | `PageFailed`: isolate in a worker process, fall back, continue the batch |
| Low quality | §9.3 | Not an error: `LowConfidence` outcome → retry ladder → fallback |

Run engines in **worker processes**. This bounds memory and allows hard kills, as
OCRmyPDF does by spawning `tesseract` as a subprocess ([omp-exec]).

### 9.6 Open questions for #13

* Should calibration curves (raw → [0, 1]) ship per engine/model, or be computed
  on the fly from agreement between retry attempts?
* Is `pytesseract` (CLI wrapper: simple, killable) or `tesserocr` (C API:
  faster, no process spawn, deadline only covers recognition) the v1 binding?
  The [local] finding favours subprocess isolation for fault tolerance.
* Do we need bold/italic? Tesseract LSTM doesn't emit it ([local]), so
  styling would have to come from another source or be dropped (the SPEC already says "no
  styling").

---

## Appendix A: local experiment

Script: ImageMagick renders 232 words of *Pride and Prejudice* (Times New
Roman 11 pt, 300 DPI, 4.5 in measure). It derives low-resolution variants (Box
downsample, Lanczos upsample), skewed variants (`-rotate`, then
`-deskew 40%`), a 90° rotation, and a "dirty" variant (multiply by a
barycentric gradient from 55% grey to white, `-blur 0x1`, Gaussian noise
0.6). Each is OCR'd with `tesseract … --dpi N -l eng [opts] tsv`. CER/WER are
Levenshtein distances on whitespace-normalised text. Tesseract 5.5.0,
Leptonica 1.85.0, macOS, eng = tessdata_fast (4.1 MB). tessdata_best eng
came from [tessdata_best][tdbest].

| Variant | Setting | CER | WER | Mean word conf |
|---|---|---|---|---|
| clean 300 DPI | any of psm 3/4/6, Otsu/adaptive/Sauvola, no-dict | 0.00% | 0.00% | 96 |
| 100 DPI | default | 1.08% | 1.72% | 93.0 |
| 100 → 300 upscaled | default | 0.00% | 0.00% | 96.0 |
| 75 DPI | default | 2.25% | 13.36% | 77.1 |
| 75 → 300 upscaled | default / Sauvola / adaptive Otsu | 0.17% / 0.25% / 0.33% | 0.86% / 1.29% / 2.16% | 95 |
| skew 1° | default | 0.08% | 0.86% | 96.2 |
| skew 3° | psm 3 / psm 4 / **psm 6** | 57.5% / 71.5% / **0.42%** | 58.2% / 78.9% / 1.72% | **95.1** / 95.1 / 95.5 |
| skew 6° | psm 3 / psm 6 | 95.8% / 3.84% | 96.6% / 19.4% | 94.0 / 91.8 |
| skew 3° or 6° → deskew | psm 3 | 0.00% | 0.00% | 96.3 |
| rot 90° | psm 3 / psm 1 | 0.00% | 0.00% | 96.1 |
| dirty 300 DPI | Otsu / adaptive Otsu / **Sauvola** / psm 6 | 0.75% / 0.17% / **0.00%** / 3.25% | 1.72% / 0.43% / 0.00% / 4.74% | 95.9 / 95.8 / 96.3 / 91.8 |
| dirty 150 DPI | Otsu / Sauvola / **adaptive Otsu** | 0.00% / 0.00% / **8.09%** | 0.00% / 0.00% / 9.05% | 95.8 / 96.1 / 94.3 |

Skew-3° bag-of-words check: psm 3 returned 98 of 232 words, all high
confidence. The missing lines were dropped, not misread.

fast vs best (eng), CER, then wall time:

| Variant | fast | best |
|---|---|---|
| 75 DPI | 2.25%, 0.5 s | 4.34%, 1.1 s |
| 100 DPI | 1.08%, 0.6 s | 1.08%, 1.2 s |
| dirty 300 | 0.75%, 1.3 s | 0.58%, 2.5 s |
| dirty 150 + adaptive Otsu | 8.09%, 0.9 s | 7.84%, 1.8 s |
| skew 6° psm 6 | 3.84%, 0.9 s | 5.84%, 1.9 s |
| clean 300 | 0.00%, 0.9 s | 0.00%, 2.2 s |

Word-confidence calibration (fast; words aligned to ground truth, pooled over
degraded cases; n = 1370):

| conf | n | correct |
|---|---|---|
| < 50 | 29 | 62% |
| 50–70 | 80 | 82% |
| 70–85 | 84 | 80% |
| 85–93 | 104 | 81% |
| ≥ 93 | 1073 | 99% |

OSD on the 90° page: `Orientation in degrees: 90, Rotate: 270, Orientation
confidence: 26.45, Script: Latin, Script confidence: 10.11` (above OCRmyPDF's
threshold of 14).

**Limitations:** one font, one synthetic page, synthetic degradations, no real
paper texture, bleed-through or curvature. Re-run on the real scanned-book corpus
before fixing thresholds.

---

## Sources

[iq]: https://tesseract-ocr.github.io/tessdoc/ImproveQuality.html
[datafiles]: https://tesseract-ocr.github.io/tessdoc/Data-Files.html
[rel]: https://tesseract-ocr.github.io/tessdoc/ReleaseNotes.html
[faq]: https://tesseract-ocr.github.io/tessdoc/FAQ.html
[cliuse]: https://tesseract-ocr.github.io/tessdoc/Command-Line-Usage.html
[man]: https://man.archlinux.org/man/tesseract.1.en
[local-params]: https://github.com/tesseract-ocr/tesseract/blob/main/src/ccmain/tesseractclass.cpp
[baseapi]: https://github.com/tesseract-ocr/tesseract/blob/main/include/tesseract/baseapi.h
[ocrclass]: https://github.com/tesseract-ocr/tesseract/blob/main/include/tesseract/ocrclass.h
[pubtypes]: https://github.com/tesseract-ocr/tesseract/blob/main/include/tesseract/publictypes.h
[tess-lic]: https://github.com/tesseract-ocr/tesseract/blob/main/LICENSE
[tdbest]: https://github.com/tesseract-ocr/tessdata_best
[willus]: https://groups.google.com/g/tesseract-ocr/c/Wdh_JJwnw94/m/24JHDYQbBQAJ
[omp-cook]: https://ocrmypdf.readthedocs.io/en/latest/cookbook.html
[omp-adv]: https://ocrmypdf.readthedocs.io/en/latest/advanced.html
[omp-intro]: https://ocrmypdf.readthedocs.io/en/latest/introduction.html
[omp-lic]: https://github.com/ocrmypdf/OCRmyPDF/blob/main/LICENSE
[omp-cli]: https://github.com/ocrmypdf/OCRmyPDF/blob/main/src/ocrmypdf/cli.py
[omp-defaults]: https://github.com/ocrmypdf/OCRmyPDF/blob/main/src/ocrmypdf/_defaults.py
[omp-tess-plugin]: https://github.com/ocrmypdf/OCRmyPDF/blob/main/src/ocrmypdf/builtin_plugins/tesseract_ocr.py
[omp-exec]: https://github.com/ocrmypdf/OCRmyPDF/blob/main/src/ocrmypdf/_exec/tesseract.py
[omp-unpaper]: https://github.com/ocrmypdf/OCRmyPDF/blob/main/src/ocrmypdf/_exec/unpaper.py
[omp-pipe]: https://github.com/ocrmypdf/OCRmyPDF/blob/main/src/ocrmypdf/_pipeline.py
[omp-spec]: https://github.com/ocrmypdf/OCRmyPDF/blob/main/src/ocrmypdf/pluginspec.py
[omp-tree]: https://github.com/ocrmypdf/OCRmyPDF/tree/main/tests/plugins
[unpaper]: https://github.com/unpaper/unpaper
[unpaper-ip]: https://github.com/unpaper/unpaper/blob/main/doc/image-processing.md
[unpaper-bc]: https://github.com/unpaper/unpaper/blob/main/doc/basic-concepts.md
[sta]: https://github.com/4lex4/scantailor-advanced
[av-req]: https://developer.apple.com/documentation/vision/vnrecognizetextrequest
[av-level]: https://developer.apple.com/documentation/vision/vnrecognizetextrequest/recognitionlevel
[av-mth]: https://developer.apple.com/documentation/vision/vnrecognizetextrequest/minimumtextheight
[av-cw]: https://developer.apple.com/documentation/vision/vnrecognizetextrequest/customwords
[av-conf]: https://developer.apple.com/documentation/vision/vnrecognizedtext/confidence
[av-top]: https://developer.apple.com/documentation/vision/vnrecognizedtextobservation/topcandidates(_:)
[av-cpu]: https://developer.apple.com/documentation/vision/vnrequest/usescpuonly
[av-bg]: https://developer.apple.com/documentation/vision/vnrequest/preferbackgroundprocessing
[av-docreq]: https://developer.apple.com/documentation/vision/recognizedocumentsrequest
[pp-doc]: https://www.paddleocr.ai/latest/en/version3.x/pipeline_usage/OCR.html
[pp-hf]: https://huggingface.co/PaddlePaddle/PP-OCRv5_server_rec
[rapid]: https://github.com/RapidAI/RapidOCR
[rapid-params]: https://rapidai.github.io/RapidOCRDocs/main/install_usage/rapidocr/parameters/
[doctr-doc]: https://mindee.github.io/doctr/using_doctr/using_models.html
[doctr-hf]: https://huggingface.co/Felix92/doctr-torch-parseq-multilingual-v1
[easy]: https://github.com/JaidedAI/EasyOCR
[easy-doc]: https://www.jaided.ai/easyocr/documentation/
[surya]: https://github.com/datalab-to/surya
[surya-hf]: https://huggingface.co/datalab-to/surya-ocr-2
[hegg]: https://doi.org/10.1007/s42001-021-00149-1
[rdt]: https://www.dfki.de/web/forschung/projekte-publikationen/publikation/4338
[lund]: https://biomedicaloptics.spiedigitallibrary.org/profile/Douglas.Kennard-78646
[sauvola]: https://doi.org/10.1016/S0031-3203(99)00055-2
[uvdoc]: https://arxiv.org/abs/2302.02887
[survey]: https://doi.org/10.1145/3453476
[dirty]: https://arxiv.org/abs/2110.11934
[ppa]: https://doi.org/10.1145/3685650.3685669
[nofree]: https://arxiv.org/abs/2502.01205

* Tesseract: [ImproveQuality][iq], [Data-Files][datafiles], [ReleaseNotes][rel], [FAQ][faq], [Command-Line Usage][cliuse], [man page][man], [baseapi.h][baseapi], [ocrclass.h][ocrclass], [publictypes.h][pubtypes], [parameter definitions (source of `--print-parameters`)][local-params], [LICENSE][tess-lic], [tessdata_best][tdbest], [Willus resolution test (tesseract-ocr list)][willus]
* OCRmyPDF: [cookbook][omp-cook], [advanced][omp-adv], [introduction][omp-intro], [LICENSE][omp-lic], [cli.py][omp-cli], [_defaults.py][omp-defaults], [tesseract_ocr.py][omp-tess-plugin], [_exec/tesseract.py][omp-exec], [_exec/unpaper.py][omp-unpaper], [_pipeline.py][omp-pipe], [pluginspec.py][omp-spec], [test plugins][omp-tree]
* Preprocessors: [unpaper][unpaper], [unpaper image processing][unpaper-ip], [unpaper basic concepts][unpaper-bc], [ScanTailor Advanced][sta]
* Apple Vision: [VNRecognizeTextRequest][av-req], [recognitionLevel][av-level], [minimumTextHeight][av-mth], [customWords][av-cw], [VNRecognizedText.confidence][av-conf], [topCandidates][av-top], [usesCPUOnly][av-cpu], [preferBackgroundProcessing][av-bg], [RecognizeDocumentsRequest][av-docreq] (Apple pages are JS-rendered; content was read from `developer.apple.com/tutorials/data/documentation/vision/<page>.json`)
* Other engines: [PaddleOCR OCR pipeline][pp-doc], [PP-OCRv5 HF card][pp-hf], [RapidOCR][rapid], [RapidOCR parameters][rapid-params], [docTR models][doctr-doc], [docTR HF weights][doctr-hf], [EasyOCR][easy], [EasyOCR docs][easy-doc], [Surya][surya], [Surya OCR 2 HF][surya-hf]. Licences for repos without a fetched LICENSE page were read with `gh api repos/<owner>/<repo> --jq .license.spdx_id`.
* Papers: [Hegghammer 2022, J. Comput. Soc. Sci.][hegg], [Rangoni, Shafait & Breuel — recognition-driven thresholding][rdt], [Lund, Kennard & Ringger, DRR 2013][lund], [Sauvola & Pietikäinen 2000][sauvola], [UVDoc, SIGGRAPH Asia 2023][uvdoc], [Nguyen et al., Survey of post-OCR processing, ACM CSUR 2021][survey], [Kim et al., Cleaning Dirty Books, EMNLP Findings 2021][dirty], [Zhang et al., DocEng 2024][ppa], [Kanerva et al., No Free Lunches, 2025][nofree]
