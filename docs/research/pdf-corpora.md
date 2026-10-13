# Free real-world PDF corpora for evaluation

Research for [#11](https://github.com/Bezoar/pdf2epub/issues/11). Researched 2026-10-13.

**Question.** Which free archives of real-world PDFs can we use to check pdf2epub
on PDFs in the wild, beyond synthetic fixtures? For each one: what may be
committed to this MIT-licensed repo, what may be fetched in CI, and what should
stay local-only.

Claims are cited to the source that owns them. Where I checked a file myself
(page count, producer, encryption, text layer, SHA-256), the note says
"verified locally". I did that with pypdf 6.x on files downloaded on 2026-10-13.

## TL;DR

- **Don't commit third-party PDFs.** Even "free" sources come with conditions:
  CC BY-SA or NC terms, Google's usage guidelines, or "at your own risk" copyright
  disclaimers. Commit a **manifest** (URL + SHA-256 + license + expected
  properties) plus a fetch script, and cache the downloads outside git. The only
  PDFs worth committing are ones we generate ourselves (SPEC §11 already plans
  for these).
- **v1 smoke set:** 15 files from the Internet Archive, arXiv (CC BY), NASA
  (US government work), Cory Doctorow (CC BY-NC-SA), and the pdf.js, qpdf and
  py-pdf test suites, all pinned by commit or hash. See
  [Recommendation A](#a-v1-smoke-test-set-15-files).
- **Ground truth comes cheap for scanned novels.** Several Internet Archive scans
  of *Pride and Prejudice* can be scored against
  [Project Gutenberg #1342](https://www.gutenberg.org/ebooks/1342), and PMC gives
  each article's PDF alongside its JATS XML.
- **Spec correction.** SPEC §11 lists "Project Gutenberg" as a source of
  real-world PDFs, but Gutenberg publishes no PDFs. Its formats are html, txt,
  epub, kindle and mp3
  ([robot access policy](https://www.gutenberg.org/policy/robot_access.html)).
  Gutenberg's role here is ground-truth text.
- **Watch out for existing OCR layers.** Every Internet Archive "Text PDF" I
  checked already has an OCR text layer, so `--ocr auto` would *not* run
  Tesseract on it. To exercise the Tesseract path, use an image-only scan, such
  as an Internet Archive "Image Container PDF" from Google Books (Recommendation
  A, file S8).
- **Future quality-metrics corpus:** use olmOCR-bench (ODC-BY, 1,403 PDFs with
  unit-test ground truth) plus a scripted PMC-OA CC BY sample (PDF and JATS
  XML), plus Internet Archive public-domain scans paired with Gutenberg texts.
  For robustness and fuzzing, sample from SafeDocs CC-MAIN-2021-31 (7.9M PDFs),
  locally only. See [Recommendation B](#b-future-quality-metrics-corpus).

## Comparison table

Key to the "Use" column:
- **commit**: may be committed with attribution.
- **CI**: fine to fetch in CI from a pinned URL.
- **local**: download only on a developer machine. Don't redistribute, and
  don't run in CI by default.

| Source | Content type | License / terms | Redistribution? | Size | Ground truth | Programmatic access | Use |
|---|---|---|---|---|---|---|---|
| **Internet Archive** (public-domain texts) | Scanned books. Most "Text PDF"s carry IA's OCR layer. "Image Container PDF"s are original uploads, often image-only. | IA "does not make guarantees as to the copyright status of items"; users must use the collections "at their own risk and ensure that such use is non-infringing" ([IA rights help](https://help.archive.org/help/rights/)). Per-item metadata such as `possible-copyright-status: NOT_IN_COPYRIGHT` or a `licenseurl` like PDM 1.0 ([example](https://archive.org/metadata/haggardkingsolomonsmines)). | Underlying US public-domain works: yes in the US. But IA disclaims rights status, so don't commit the PDFs. | Millions of texts. Books in the smoke set are 8–150 MB (verified locally). | IA's OCR outputs (`_djvu.txt`, `_hocr.html`) are references, not ground truth. Pair with Gutenberg text for true ground truth. | [Metadata API](https://archive.org/developers/md-read.html) (lists files with size and SHA-1), `archive.org/download/{id}/{file}`, [`internetarchive` Python library and CLI](https://archive.org/developers/internetarchive/), `advancedsearch.php`. | CI (pinned id, file and SHA-1) or local |
| **HathiTrust** full-view | Scanned books. | Guests may download whole public-domain volumes only when the volume has no download restrictions. Google-digitized volumes are page-at-a-time for guests, and full PDFs require login through a member institution ([HathiTrust help: What you can download](https://hathitrust.atlassian.net/wiki/x/IYBKjg)). | Underlying public-domain text: yes. Bulk download of Google scans is restricted by contract. | Millions of volumes. | OCR text (as a member or through a dataset request). | Web UI. The site sits behind bot protection (hathitrust.org returned HTTP 403 to my scripted fetches). | Local, manual only. Prefer IA copies of the same books. |
| **Google Books** public-domain PDFs | Scanned books, image-only plus a guidelines page. | The first page of every PDF asks users to "Make non-commercial use of the files", "Refrain from automated querying", and "Maintain attribution… Please do not remove [the watermark]" (verified locally in `hassanafellahar00gillgoog.pdf`). | Request-based restrictions, not a license. Don't commit. | n/a | None | No automated querying permitted. Get the same scans through IA mirrors (`*goog` identifiers). | Local. Use the IA mirror instead. |
| **Project Gutenberg** | **No PDFs.** Text, HTML and EPUB only ([robot policy](https://www.gutenberg.org/policy/robot_access.html)). | For US public-domain works, strip the PG trademark and license and "You can do anything you want with that text in the United States" ([PG license](https://www.gutenberg.org/policy/license.html)). The catalog is public domain. | Text: yes, once PG references are removed. | Tens of thousands of books. | **This is the ground truth.** Clean transcriptions of the same works IA scanned. | Human use only, except `wget` harvesting from `/robot/harvest` or private mirrors ([robot policy](https://www.gutenberg.org/policy/robot_access.html)). Cache texts once. | Ground-truth text: commit after stripping, or fetch in CI |
| **Standard Ebooks** | No PDFs (EPUB and AZW3). | CC0 1.0 for their own work ([about](https://standardebooks.org/about)). | Yes | n/a | Clean text and EPUB structure, useful as a reference EPUB. | Website downloads | Reference only |
| **arXiv** | Born-digital papers, often two-column. | Default arXiv license gives arXiv alone the right to distribute and "limits re-use of any type from other entities" ([arXiv licenses](https://info.arxiv.org/help/license/index.html)). The API ToU allows storing content "for your own personal use, or for research purposes", but "redistribution of e-prints requires permission from the copyright holder" ([API ToU](https://info.arxiv.org/help/api/tou.html)). Some papers are CC BY, BY-SA or CC0. Each paper's license is in OAI-PMH metadata. | Only the CC BY, BY-SA and CC0 subset, with attribution. | About 2.7 TB of PDFs (Mar 2023), growing about 100 GB/month ([bulk S3](https://info.arxiv.org/help/bulk_data_s3.html)). | LaTeX source (`src/`) can serve as ground truth for text and structure. | API at most 1 request per 3 s on a single connection ([ToU](https://info.arxiv.org/help/api/tou.html)). Requester-pays bucket `s3://arxiv/pdf/` with manifest XML ([bulk S3](https://info.arxiv.org/help/bulk_data_s3.html)). OAI-PMH `metadataPrefix=arXiv` gives `<license>`. | CI (a few CC BY papers, pinned version) or local |
| **PubMed Central OA subset** | Born-digital journal articles, often two-column. | Covers articles "made available under Creative Commons or similar licenses". "Refer to the license statement in each article". "Systematic retrieval… through any other automated process is prohibited", so use the listed services ([PMC OA](https://pmc.ncbi.nlm.nih.gov/tools/openftlist/)). | Per article. The CC BY ones: yes, with attribution. | Very large (the whole OA subset). | **JATS XML with full text and structure**, plus plain text, next to each PDF ([AWS registry](https://registry.opendata.aws/ncbi-pmc/)). | `s3://pmc-oa-opendata` (us-east-1, no AWS account needed) with a CSV inventory ([AWS registry](https://registry.opendata.aws/ncbi-pmc/)). | CI (small CC BY sample) or local |
| **NASA publications** (e.g. the [NASA History Series](https://www.nasa.gov/history/history-publications-and-resources/nasa-history-series/)) | Born-digital non-fiction with photos, and some scans with OCR. | NASA material is "generally not subject to copyright in the United States". Third-party material inside is excluded ([NASA media guidelines](https://www.nasa.gov/nasa-brand-center/images-and-media/)). | Mostly yes. Check embedded third-party images. | Hundreds of books. | None | Direct PDF URLs. They have moved before (2023 site migration), so pin by SHA-256. | CI or local |
| **SafeDocs CC-MAIN-2021-31-PDF-UNTRUNCATED** | Crawled mixed web PDFs, including broken ones. | Defers to "Common Crawl's license and terms of use" ([dataset page](https://digitalcorpora.org/corpora/file-corpora/cc-main-2021-31-pdf-untruncated/)). CC ToU: crawled content "may be subject to separate terms"; "you agree to respect the copyrights… of third parties" ([CC ToU](https://commoncrawl.org/terms-of-use)). | No. Third-party copyright applies. | About 7.9M unique PDFs, about 8 TB, in 7,933 zips of 1,000 files each ([dataset page](https://digitalcorpora.org/corpora/file-corpora/cc-main-2021-31-pdf-untruncated/)). | None. `pdfinfo` and Tika metadata CSVs. | `s3://digitalcorpora/corpora/files/CC-MAIN-2021-31-PDF-UNTRUNCATED/` and HTTPS mirror. Zip `NNNN.zip` holds `NNNN000–NNNN999.pdf`. | Local (robustness and batch testing) |
| **GovDocs1** | Crawled mixed .gov files, about 1M files of all types, many PDFs. | "Freely available for research and may be (to the best of our knowledge) freely redistributed". It **contains intentionally retained malware and JS exploits** ([GovDocs1 page](https://digitalcorpora.org/corpora/file-corpora/files/)). Site content is CC0, but "any material that explicitly claims a copyright is not subject to the CC0 license" ([Digital Corpora ToU](https://digitalcorpora.org/about-digitalcorpora/terms-of-use/)). | Mostly yes (US government sources). | About 986k files. Ten 1,000-file `subset*.zip` exist for pilots ([GovDocs1 page](https://digitalcorpora.org/corpora/file-corpora/files/)). | None | `https://downloads.digitalcorpora.org/corpora/files/govdocs1/` (dirs, zips, MD5/SHA-1 lists). | Local, in a sandbox (malware) |
| **DocLayNet** | Born-digital single pages: financial, scientific, legal, tenders, manuals, patents. | CDLA-Permissive-1.0 ([LICENSE](https://github.com/DS4SD/DocLayNet/blob/main/LICENSE)). | Yes (CDLA-P) | 80,863 pages. Core 28 GiB, `DocLayNet_extra.zip` (per-page PDFs + JSON) 7.5 GiB ([README](https://github.com/DS4SD/DocLayNet)). | **Human-annotated layout boxes** (11 classes, COCO), plus text cells with coordinates. | IBM COS zip, HF `ds4sd/DocLayNet` ([README](https://github.com/DS4SD/DocLayNet)). | CI (a sample) or local |
| **PubLayNet** | Pages of biomedical articles. | Annotations CDLA-Permissive-1.0. Images and PDFs must follow PMC OA terms ([LICENSE.md](https://github.com/ibm-aur-nlp/PubLayNet/blob/master/LICENSE.md)). | Annotations yes. PDFs per PMC article. | Built by matching more than 1M PMC articles ([paper](https://arxiv.org/abs/1908.07836)). | Auto-generated layout boxes (COCO). | `PubLayNet_PDF.tar.gz` on IBM CDN ([README](https://github.com/ibm-aur-nlp/PubLayNet)). | Local |
| **olmOCR-bench** (AllenAI) | Single-page PDFs: arXiv math, old scans, tables, headers and footers, multi-column, tiny text. | ODC-BY-1.0, "intended for research and educational use" ([dataset card](https://huggingface.co/datasets/allenai/olmOCR-bench)). | Yes (ODC-BY) for the dataset. Source docs come from arXiv, IA and LoC. | 1,403 PDFs and 7,010 tests, about 357 MB ([card](https://huggingface.co/datasets/allenai/olmOCR-bench)). The repo holds the 1,403 PDFs (verified via HF API). | **Unit tests**: text presence and absence, reading order, tables, math. | HF datasets (git-lfs, `huggingface_hub`), revision-pinnable. | CI (pinned revision) |
| **OmniDocBench** | 1,651 PDF pages across 10 doc types (books, newspapers, notes…) **as images**. | "For research purposes only and not for commercial use" ([HF README](https://huggingface.co/datasets/opendatalab/OmniDocBench)). Code is Apache-2.0. | No (NC data) | 1,651 pages | Rich annotations (layout, reading order, text, tables). | HF dataset | Local only. Images, not PDFs, so of limited use. |
| **pdf.js test suite** | Test suite: real-world bug-report PDFs, fonts, encryption, broken xref, fuzzed files. | Repo Apache-2.0 (verified via GitHub API). The PDFs are third-party bug attachments with no per-file license. About 1,416 manifest entries, some with `"link": true` (external URL in a `.link` file) and some with `password` (e.g. `issue6010_1.pdf` / `abc`) ([test_manifest.json](https://github.com/mozilla/pdf.js/blob/master/test/test_manifest.json)). | Unclear per file. Don't commit. Fetch from a pinned commit. | Hundreds of committed PDFs plus links | Reference render snapshots (pdf.js-specific). | `raw.githubusercontent.com/mozilla/pdf.js/<sha>/test/pdfs/<file>` | CI |
| **qpdf test suite** | Test suite: every encryption revision (RC4-40 to AES-256 R6), damaged xref and streams, issue repros. | Apache-2.0 (verified via GitHub API). | Apache-2.0 compatible. Committing would be OK with NOTICE, but fetching is simpler. | 706 PDFs in the tree at `qpdf/qtest/qpdf/` (verified via git tree API) | Expected `.out` outputs (qpdf-specific). | raw GitHub at a pinned SHA | CI |
| **py-pdf/sample-files** | Test suite: small generated PDFs (LibreOffice, pdfTeX, Google Docs…), encrypted, multicolumn, Arabic, forms. | "Every PDF in this repository is under… CC-BY-SA-4.0" ([README](https://github.com/py-pdf/sample-files)). `files.json` has per-file metadata. | Yes, with attribution and share-alike on the files. They stay separate works, so our MIT code is unaffected. | 35 PDFs | `files.json` (page count, encryption, images…). Some folders include the source `.odt` or `.tex`. | raw GitHub at a pinned SHA | CI (committing allowed but unnecessary) |
| **PDF Association pdf20examples** | Test suite: tiny PDF 2.0 files. | CC BY-SA 4.0 ([LICENSE.md](https://github.com/pdf-association/pdf20examples/blob/master/LICENSE.md)). | Yes (BY-SA) | 7 files | None | raw GitHub | CI |
| **veraPDF corpus** | Test suite: PDF/A and PDF/UA conformance cases, mostly synthetic. | CC BY 4.0 ([README](https://github.com/veraPDF/veraPDF-corpus)). | Yes | Many small files | Pass/fail per validation rule. Not text. | git | Low value for pdf2epub. Skip. |

## Recommendation

### A. v1 smoke-test set (15 files)

Use these for SPEC §12 acceptance checks and manual smoke runs. Store them as a
manifest (`tests/corpus/smoke.toml` or similar) with `url`, `sha256`, `license`,
`password` and `expect` fields. A `scripts/fetch_corpus.py` would download into
a git-ignored cache (e.g. `~/.cache/pdf2epub-corpus/`), verify SHA-256, and
skip on network failure. Tests marked `@pytest.mark.corpus` would run in a
nightly or opt-in CI job. Total download is about 70 MB, most of it the three
scanned books.

All SHA-256 values were verified locally on 2026-10-13. Pin GitHub-hosted files
to the commit SHA shown. For arXiv, NASA and IA, treat a hash mismatch as "the
upstream file changed": warn, and re-pin after review.

| # | Role (SPEC criterion) | File / identifier | Fetch URL | License | SHA-256 | Notes and ground truth |
|---|---|---|---|---|---|---|
| S1 | Novel, born-digital (§12.1) | *Little Brother*, Cory Doctorow | `https://craphound.com/littlebrother/Cory_Doctorow_-_Little_Brother.pdf` | CC BY-NC-SA 3.0 ([download page](https://craphound.com/littlebrother/download/)) | `f90e8dfe9778a6859a817a598c557c8c9963ac75a49ca2d7987ca386ad8f3700` | 134 pp, LibreOffice 6.0 Writer, running header "Cory Doctorow/Little Brother/NN". Non-commercial testing fits NC. Don't commit. |
| S2 | Non-fiction with images, born-digital | NASA SP-4319 *Revolutionary Atmosphere* (2010) | `https://www.nasa.gov/wp-content/uploads/2023/04/sp-4319.pdf` | US Gov work ([NASA guidelines](https://www.nasa.gov/nasa-brand-center/images-and-media/)) | `6a18d02a4b4be8710dd670811800b9a2819cb8b3e6fc94c3305bd805a2018321` | 414 pp, InDesign CS3, photos and captions, TOC. |
| S3 | Non-fiction with photos, scanned with an existing OCR layer | NASA SP-4553 *NASA Photo One* (2013) | `https://www.nasa.gov/wp-content/uploads/2023/03/sp-4553.pdf` | US Gov work | `e0d2684878252f5174b7f3e7c54d164924bdea758b0e8638fa1433d651160e80` | 133 pp. Creator "Canon DR-7550C TWAIN", Producer "Acrobat Paper Capture". Photo-heavy. |
| S4 | Two-column paper, CC BY (§12.3) | arXiv **2501.17887v1** (*Docling: An Efficient Open-Source Toolkit…*) | `https://arxiv.org/pdf/2501.17887v1` | CC BY 4.0 (OAI-PMH `<license>`) | `f555f6260be1de6cd8f75addca4edc3c4456b2d5f3bf01a115942cb81396208a` | 8 pp, AAAI two-column, figures and tables. LaTeX source is available as ground truth. Respect the 3 s rate limit. |
| S5 | Two-column paper, classic | pdf.js `tracemonkey.pdf` (PLDI '09 paper) | `https://raw.githubusercontent.com/mozilla/pdf.js/288892aadaa27f03ed0cd4724edf678c6bda8e61/test/pdfs/tracemonkey.pdf` | In Apache-2.0 repo. Paper rights unclear, so fetch only. | `3662ff519e485810520552bf301d8c3b2b917fd2f83303f4965d7abed367e113` | 14 pp, pdfeTeX, Type1 fonts, charts drawn as text glyphs. |
| S6 | Multi-column LaTeX, tiny | py-pdf `026-latex-multicolumn/multicolumn.pdf` | `https://raw.githubusercontent.com/py-pdf/sample-files/02b8203bf416db3dbdb03438bc8278dfcb0555f3/026-latex-multicolumn/multicolumn.pdf` | CC BY-SA 4.0 | `bdb495e95b3e1afae95013099dc59b0cea047f1fa70f677ee9cb33f10faa1c6c` | 3 pp. Fast enough for every CI run. |
| S7 | Scanned book, clean (§12.2) | IA `prideprejudicewi00austuoft` (1906, U. Toronto, Scribe scan) | `https://archive.org/download/prideprejudicewi00austuoft/prideprejudicewi00austuoft.pdf` | PD (US). IA "at your own risk". | `77bb1627dd1a03ab1a5308f3d96cb2703e4bbe08ed62ba15d1418ba02be77d79` (IA SHA-1 `64d06ac3…441b`) | 360 pp, **has IA OCR layer**. Ground truth: [PG #1342](https://www.gutenberg.org/ebooks/1342) minus the introduction. Tests `--ocr auto` and mojibake detection on an existing layer. Run with `--ocr always` to exercise Tesseract. |
| S8 | Scanned book, degraded, **image-only** (§12.2) | IA `hassanafellahar00gillgoog` (1898, Google scan) | `https://archive.org/download/hassanafellahar00gillgoog/hassanafellahar00gillgoog.pdf` | PD (`NOT_IN_COPYRIGHT`). Google usage guidelines on p.1. Local or CI, never commit. | `32df99306fb45d47d04d050db891d5a4052cb2f95b7db7136eb80d272a72b724` | 614 pp, "Google Books PDF Converter". **No text layer except the p.1 guidelines page** (verified), so `--ocr auto` must trigger Tesseract. Google watermark on every page. Reference: IA `_djvu.txt`. |
| S9 | Scanned book, degraded (microfiche) | IA `cihm_990165` (*Pride and Prejudice*, 1919, Canadiana microfiche) | `https://archive.org/download/cihm_990165/cihm_990165.pdf` | PD (pre-1929 US pub.) | `d4cbabed17bddae01bb449d9686067f40cc0254fa37b8d16fe7fbefc000923a8` | 291 pp, low-contrast microfiche with IA OCR layer. Ground truth: PG #1342, the same text as S7, so the two give a direct clean-vs-degraded comparison. |
| S10 | Encrypted, AES-256 (R6), user password | qpdf `enc-XI-R6,V5,U=view,O=master.pdf` | `https://raw.githubusercontent.com/qpdf/qpdf/4eba95899886e851cc41d76886483b347612f2a8/qpdf/qtest/qpdf/enc-XI-R6,V5,U=view,O=master.pdf` (URL-encode the commas if needed) | Apache-2.0 | `96b9262bfacf1358c7a68ab46c11563677e858888950237fdac8f3a227210edf` | 30 pp. `--password view` opens it (verified). Without a password it must fail cleanly with exit 3 or a password error. |
| S11 | Encrypted, owner password only | qpdf `enc-XI-R6,V5,O=master.pdf` | `…/qpdf/qtest/qpdf/enc-XI-R6,V5,O=master.pdf` (same SHA) | Apache-2.0 | `63c99503fc9c6b44c47df124ce040d005e26d2c5d8d0999ad59c48b31a426863` | Opens with an empty user password (verified). Must convert with no `--password`. |
| S12 | Encrypted, RC4-128 (R3), user password | py-pdf `005-libreoffice-writer-password/libreoffice-writer-password.pdf` | `https://raw.githubusercontent.com/py-pdf/sample-files/02b8203bf416db3dbdb03438bc8278dfcb0555f3/005-libreoffice-writer-password/libreoffice-writer-password.pdf` | CC BY-SA 4.0 | `3e333bff0196d0c5320f40cdd1b7a3abd21b316de79de3c0f9083accdaef9358` | Password `openpassword` (owner `permissionpassword`) per [its README](https://github.com/py-pdf/sample-files/blob/main/005-libreoffice-writer-password/README.md). V=2 R=3 (verified). |
| S13 | Malformed, recoverable | pdf.js `xref_command_missing.pdf` | `https://raw.githubusercontent.com/mozilla/pdf.js/288892aadaa27f03ed0cd4724edf678c6bda8e61/test/pdfs/xref_command_missing.pdf` | Apache-2.0 repo | `88d3905774607b3f529e369db122b2d14051417993c9a704472c91c6702ccff6` | 631 bytes. pypdf recovers it with warnings (1 page). Should convert. |
| S14 | Malformed, unrecoverable (§12.4 batch) | qpdf `bad-xref.pdf` | `https://raw.githubusercontent.com/qpdf/qpdf/4eba95899886e851cc41d76886483b347612f2a8/qpdf/qtest/qpdf/bad-xref.pdf` | Apache-2.0 | `5895dfedf978f600b12e29643617dbb111869b60526d957878e349571e1467d1` | pypdf raises `PdfReadError` (verified). In a batch of 100 it must be reported, not fatal. |
| S15 | Truncated download | Derived: the first 60% of the bytes of S4 | generated by the fetch script | inherits CC BY | n/a | Simulates an interrupted download, the most common real-world breakage. No startxref or trailer. |

Coverage check against SPEC §12:

| Criterion | Files |
|---|---|
| 1, novel | S1 |
| 2, scanned | S7, S8, S9, S3 |
| 3, two-column | S4, S5, S6 |
| 4, batch with corrupt files | all 15 together, with S14 and S15 |
| Encryption (§5.1) | S10, S11, S12 |
| Images | S2, S3 |

All 15 run as one batch.

Options for more coverage:
- RTL text: py-pdf `015-arabic/habibi.pdf` (CC BY-SA).
- Outline and bookmarks: py-pdf `006-pdflatex-outline`.
- pdf.js password cases with non-ASCII passwords (`issue6010_2.pdf` / `æøå`, `issue21579.pdf` / `pässwört`). These exercise SASLprep on R6 passwords.

### B. Future quality-metrics corpus

SPEC §11 asks for character accuracy, paragraph-boundary F1, heading F1 and the
fallback rate, all tracked in CI. That needs real ground truth. In order of
value:

1. **Scanned books against Gutenberg text (character accuracy on OCR and
   scans).** Script an IA `advancedsearch.php` query that pairs public-domain
   IA scans (`possible-copyright-status:NOT_IN_COPYRIGHT`, single-column
   fiction) with Gutenberg editions of the same title. *Pride and Prejudice*
   alone has at least 30 IA `texts` items of varying quality, from Scribe and Kirtas
   to Google and microfiche (IA search, verified). Strip PG headers. Cache IA
   PDFs locally or in a CI cache keyed by SHA-1. Alignment must tolerate
   edition differences such as introductions and illustrations, for example
   with an alignment-based CER restricted to the main text.
2. **PMC-OA CC BY sample (born-digital two-column papers; paragraph and
   heading F1).** Take 200–500 articles from `s3://pmc-oa-opendata`, filtered
   to CC BY in the per-article JSON metadata. JATS XML gives the section
   headings, paragraphs and figure captions that SPEC's metrics need. This is
   the best structural ground truth available for free. Use the S3 bucket, not
   scraping, which PMC prohibits.
3. **olmOCR-bench (ODC-BY) for reading order, headers and footers, and
   multi-column.** The PDFs and unit tests are pinnable by HF revision
   `54a96a6f…` (2026-10-13). Its `headers_footers`, `multi_column` and
   `old_scans` splits map directly onto pdf2epub's heuristics. It's small
   enough (357 MB) for a cached CI job. Caveat: all items are single pages, so
   it can't test cross-page paragraph joins.
4. **DocLayNet extra (CDLA-Permissive) for heading and caption
   classification.** Per-page PDFs with human layout labels (Title,
   Section-header, Caption, Page-header, Page-footer, Footnote…). Use it to
   score the layout analyzer's block classes, sampled (e.g. 1k pages).
5. **Robustness and batch-scale tests, local only.** Use one or two SafeDocs
   CC-MAIN-2021-31 zips (1,000 real-world PDFs each, about 1–2.8 GB) to check
   "no crashes, bounded time". The `pdfinfo` and Tika metadata CSVs help you
   stratify by producer, encryption and page count. Use the GovDocs1
   `subset0.zip` only in a sandbox, because it contains intentional malware.
   Never commit or redistribute files from either.

Skip for metrics:
- HathiTrust: guest bulk access is blocked for Google scans, and the site is
  bot-protected.
- Google Books: "no automated querying".
- OmniDocBench: non-commercial, and ships images, not PDFs.
- veraPDF corpus: conformance-oriented, so little text.

## Repo policy suggestions

- Keep `tests/fixtures/` for **self-generated** PDFs only (ReportLab, LaTeX or
  Typst output plus their sources). These can be MIT/CC0.
- Real-world files: commit the manifest plus the fetch script only. Record the
  license and attribution for each entry in the manifest. This satisfies CC BY
  and BY-SA attribution without bringing share-alike files into the tree.
- If you ever need a committed real-world file (e.g. an offline CI
  requirement), the cleanest candidates are the qpdf (Apache-2.0) and py-pdf
  (CC BY-SA 4.0) samples. Add a `tests/fixtures/THIRD_PARTY.md` with their
  license notices.
