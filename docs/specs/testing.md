# Test assets and measurement

**Status:** accepted · **Depends on:** [main](main.md), [api](api.md), [passwords](passwords.md), [reflow](reflow.md), [ocr](ocr.md), [epub](epub.md) · **Decisions:** [Implementation language and packaging](https://github.com/Bezoar/pdf2epub/issues/7), [Free real-world PDF corpora for evaluation](https://github.com/Bezoar/pdf2epub/issues/11), [v1 scope cut and roadmap contents](https://github.com/Bezoar/pdf2epub/issues/6), [Text-layer quality check](https://github.com/Bezoar/pdf2epub/issues/15), [Plan and build-ticket format](https://github.com/Bezoar/pdf2epub/issues/16)

This spec covers the product's test **assets** and **measurements**: synthetic fixtures, the committed public-domain sample, the real-world smoke set, how OCR accuracy is measured, and the CI checks that tie tests to specs (the acceptance-criterion marker gate, event-schema validation, epubcheck). How to write tests (red-green, what counts as a tautological test, coverage rules, test layout) is process, and lives in [coding instructions](../instructions/coding.md). Which fixture each build ticket creates is recorded in the plan's fixture table ([plan](../plans/v1.md)).

## 1. Synthetic fixtures

<a id="tst-r1"></a>**TST-R1**: Synthetic fixtures shall be produced by generator scripts in the repo, and the generated files shall be committed. Generators shall be deterministic: running a generator twice with the same tool versions yields byte-identical files (fixed seeds, fixed timestamps and document IDs).

<a id="tst-r2"></a>**TST-R2**: Generators use ReportLab for born-digital PDFs, Pillow (with NumPy) for scanned variants and pypdf for encrypted variants. ReportLab is the only dev-only addition; Pillow, NumPy and pypdf are runtime dependencies anyway ([main](main.md#main-r13)), so fixture generation adds no runtime dependency. Each fixture generated from text shall also commit that text as its **ground truth**.

<a id="tst-r3"></a>**TST-R3**: The synthetic set shall include at least:

| Group | Fixtures |
|---|---|
| Born-digital | a multi-chapter single-column novel with a PDF outline, running headers and footers, page numbers, paragraphs split across pages and hyphenated line ends; the same without an outline (chapter headings only); a two-column page set; a page with a table and a page with math (complex pages); a blank page; italic and bold runs; a verse-and-code sample (a poem between prose paragraphs, and a monospace code block crossing a page break) |
| Scanned | the novel's pages rendered to images at 300 DPI (clean); variants with noise, 2° skew, 90° rotation, and at 150 DPI (degraded); an image-only scan with no text layer; a scan with a good invisible OCR layer |
| Encrypted | Standard handler AES-256 (R6) with a user password; AES-128 (R4) with a user password; RC4-128 (R3) with a user password; owner-password-only with copy/extract forbidden (opens with the empty password, `restricted`); owner-password-only with all permissions; a non-Standard security handler (e.g. a `/Filter /FOPN_foweb` Encrypt dictionary) for `drm_protected` |
| Must reject (text layer) | a font with no ToUnicode map, so text extracts as Private Use Area code points or garbage; a garbled invisible OCR layer (real characters, nonsense words); an invisible OCR layer covering only half of each page |
| Damaged | a truncated file; a file with a broken cross-reference table that a parser can repair; a non-PDF file with a `.pdf` name; a zero-page document; an image that exceeds the decompression limits |
| Page numbers | a scanned book with one printed page missing and one printed page repeated, plus roman-numeral front matter and an unnumbered chapter opener |

<a id="tst-r4"></a>**TST-R4**: The **must-trust** set for the text-layer quality check ([ocr](ocr.md#ocr-r8)) shall be every born-digital page of the smoke set plus the existing text layers of the Internet Archive scans in it (S7, S9). The **must-reject** set shall be the three must-reject fixtures in [TST-R3](#tst-r3). Both are regression tests; the smoke-set part runs in the smoke job ([§3](#3-real-world-smoke-set)), the synthetic part in every CI run.

## 2. Public-domain sample

<a id="tst-r5"></a>**TST-R5**: A public-domain sample shall be committed under `tests/fixtures/public-domain/`. It shall contain only clearly public-domain sources: Internet Archive scans of works published before 1930, US-government NASA PDFs, and the image-only Google scan via its Internet Archive mirror. *Little Brother* (CC BY-NC-SA) shall not be committed; it stays fetch-only.

<a id="tst-r6"></a>**TST-R6**: `tests/fixtures/public-domain/PROVENANCE.md` shall list, for every file: the source URL, the public-domain basis (e.g. "US government work", "published 1906, US public domain"), the SHA-256 of the committed file, and the page range kept.

<a id="tst-r7"></a>**TST-R7**: The public-domain sample shall total at most about 30 MB, shall not use Git LFS, and large books shall be trimmed to representative page ranges with pypdf.

<a id="tst-r8"></a>**TST-R8**: No third-party PDF other than the public-domain sample shall be committed. Every other real-world file is fetched by the smoke script.

## 3. Real-world smoke set

<a id="tst-r9"></a>**TST-R9**: The smoke set shall be described by a committed manifest (`tests/corpus/smoke.toml`). Each entry has `id`, `url`, `sha256`, `license`, `password` (or none) and `expect`. The `password` values are the test passwords that the upstream test suites (qpdf, py-pdf) publish alongside those public files. They are not user secrets, and committing them doesn't conflict with [PWD-R26](passwords.md#pwd-r26), which governs what pdf2epub itself writes when it runs. The same applies to the fixed passwords of the synthetic encrypted fixtures (the expected outcome and key issue codes under the current specs).

<a id="tst-r10"></a>**TST-R10**: `scripts/smoke.py` shall download each manifest entry into a cache outside git (default `~/.cache/pdf2epub-corpus/`), verify its SHA-256, reuse cached files whose hash matches, derive generated entries (S15) locally, run pdf2epub over the whole set as **one batch**, and compare each conversion against its `expect`. A hash mismatch shall be reported as "upstream file changed" for that entry, which is skipped until someone reviews and re-pins it. A network failure skips the entry with a message; it is not a test failure.

<a id="tst-r11"></a>**TST-R11**: A manually triggered CI workflow shall run the smoke script. It shall never gate a PR or a merge.

<a id="tst-r12"></a>**TST-R12**: The v1 smoke set shall be these 15 files (all SHA-256 values verified on 2026-10-13; GitHub-hosted files are pinned to a commit):

| # | Role | File | Fetch URL | Licence | SHA-256 | Expectation |
|---|---|---|---|---|---|---|
| S1 | Novel, born-digital | *Little Brother*, Cory Doctorow (134 pp, running header "Cory Doctorow/Little Brother/NN") | `https://craphound.com/littlebrother/Cory_Doctorow_-_Little_Brother.pdf` | CC BY-NC-SA 3.0 (fetch only) | `f90e8dfe9778a6859a817a598c557c8c9963ac75a49ca2d7987ca386ad8f3700` | `converted`; chapter TOC; no running headers or page numbers in text |
| S2 | Non-fiction with images, born-digital | NASA SP-4319 *Revolutionary Atmosphere* (414 pp) | `https://www.nasa.gov/wp-content/uploads/2023/04/sp-4319.pdf` | US government work | `6a18d02a4b4be8710dd670811800b9a2819cb8b3e6fc94c3305bd805a2018321` | `converted`; images with captions |
| S3 | Photo-heavy, scanned with an existing OCR layer | NASA SP-4553 *NASA Photo One* (133 pp) | `https://www.nasa.gov/wp-content/uploads/2023/03/sp-4553.pdf` | US government work | `e0d2684878252f5174b7f3e7c54d164924bdea758b0e8638fa1433d651160e80` | `converted` |
| S4 | Two-column paper | arXiv 2501.17887v1 (*Docling*, 8 pp) | `https://arxiv.org/pdf/2501.17887v1` | CC BY 4.0 | `f555f6260be1de6cd8f75addca4edc3c4456b2d5f3bf01a115942cb81396208a` | `converted`; two-column pages as `page_fallback` reason `multi_column`; never interleaved |
| S5 | Two-column paper, classic | pdf.js `tracemonkey.pdf` (14 pp) | `https://raw.githubusercontent.com/mozilla/pdf.js/288892aadaa27f03ed0cd4724edf678c6bda8e61/test/pdfs/tracemonkey.pdf` | in an Apache-2.0 repo; paper rights unclear (fetch only) | `3662ff519e485810520552bf301d8c3b2b917fd2f83303f4965d7abed367e113` | as S4 |
| S6 | Multi-column LaTeX, tiny | py-pdf `026-latex-multicolumn/multicolumn.pdf` (3 pp) | `https://raw.githubusercontent.com/py-pdf/sample-files/02b8203bf416db3dbdb03438bc8278dfcb0555f3/026-latex-multicolumn/multicolumn.pdf` | CC BY-SA 4.0 | `bdb495e95b3e1afae95013099dc59b0cea047f1fa70f677ee9cb33f10faa1c6c` | as S4 |
| S7 | Scanned book, clean, with an IA OCR layer | IA `prideprejudicewi00austuoft` (1906, 360 pp) | `https://archive.org/download/prideprejudicewi00austuoft/prideprejudicewi00austuoft.pdf` | public domain (US) | `77bb1627dd1a03ab1a5308f3d96cb2703e4bbe08ed62ba15d1418ba02be77d79` | `converted`; existing layer trusted under `auto`; ground truth Project Gutenberg #1342 (without the introduction) |
| S8 | Scanned book, degraded, image-only | IA `hassanafellahar00gillgoog` (1898 Google scan, 614 pp; text layer only on the p. 1 guidelines page; watermark on every page) | `https://archive.org/download/hassanafellahar00gillgoog/hassanafellahar00gillgoog.pdf` | public domain (`NOT_IN_COPYRIGHT`); Google guidelines on p. 1 | `32df99306fb45d47d04d050db891d5a4052cb2f95b7db7136eb80d272a72b724` | `converted`; `auto` runs Tesseract on the image pages |
| S9 | Scanned book, degraded (microfiche), with an IA OCR layer | IA `cihm_990165` (*Pride and Prejudice*, 1919, 291 pp) | `https://archive.org/download/cihm_990165/cihm_990165.pdf` | public domain (US, pre-1929) | `d4cbabed17bddae01bb449d9686067f40cc0254fa37b8d16fe7fbefc000923a8` | `converted`; ground truth PG #1342, compared with S7 |
| S10 | Encrypted, AES-256 (R6), user password | qpdf `enc-XI-R6,V5,U=view,O=master.pdf` (30 pp) | `https://raw.githubusercontent.com/qpdf/qpdf/4eba95899886e851cc41d76886483b347612f2a8/qpdf/qtest/qpdf/enc-XI-R6,V5,U=view,O=master.pdf` | Apache-2.0 | `96b9262bfacf1358c7a68ab46c11563677e858888950237fdac8f3a227210edf` | password `view` ⇒ `converted`; no password ⇒ `missing_password` |
| S11 | Encrypted, owner password only, AES-256 (R6), restricted | qpdf `enc-XI-R6,V5,O=master.pdf` (30 pp) | `https://raw.githubusercontent.com/qpdf/qpdf/4eba95899886e851cc41d76886483b347612f2a8/qpdf/qtest/qpdf/enc-XI-R6,V5,O=master.pdf` | Apache-2.0 | `63c99503fc9c6b44c47df124ce040d005e26d2c5d8d0999ad59c48b31a426863` | password `master` (the owner password) ⇒ `converted` with `owner_password_used` (info). Its `/P` is `-2368`: copy/extract (bit 5) is forbidden, as are printing, modifying, annotating and form filling; only accessibility extraction and assembly are permitted. It opens with the empty password, so without `master` it would fail with `restricted` |
| S12 | Encrypted, RC4-128 (R3), user password | py-pdf `005-libreoffice-writer-password/libreoffice-writer-password.pdf` | `https://raw.githubusercontent.com/py-pdf/sample-files/02b8203bf416db3dbdb03438bc8278dfcb0555f3/005-libreoffice-writer-password/libreoffice-writer-password.pdf` | CC BY-SA 4.0 | `3e333bff0196d0c5320f40cdd1b7a3abd21b316de79de3c0f9083accdaef9358` | password `openpassword` ⇒ `converted` (owner password `permissionpassword`) |
| S13 | Malformed, recoverable | pdf.js `xref_command_missing.pdf` (631 bytes, 1 page) | `https://raw.githubusercontent.com/mozilla/pdf.js/288892aadaa27f03ed0cd4724edf678c6bda8e61/test/pdfs/xref_command_missing.pdf` | in an Apache-2.0 repo | `88d3905774607b3f529e369db122b2d14051417993c9a704472c91c6702ccff6` | `converted` with `repaired_pdf` |
| S14 | Malformed, unrecoverable | qpdf `bad-xref.pdf` | `https://raw.githubusercontent.com/qpdf/qpdf/4eba95899886e851cc41d76886483b347612f2a8/qpdf/qtest/qpdf/bad-xref.pdf` | Apache-2.0 | `5895dfedf978f600b12e29643617dbb111869b60526d957878e349571e1467d1` | `failed` with `corrupt_pdf`; batch continues |
| S15 | Truncated download | the first 60% of the bytes of S4, generated by the smoke script | — | inherits CC BY 4.0 | — (derived) | `failed` with `corrupt_pdf`, or `converted` with `repaired_pdf` |

S10–S12 run in the batch with their passwords (`view`, `master`, `openpassword`) supplied through a password map. S11's permissions were read from its Encrypt dictionary with pypdf on 2026-10-13. The run's overall exit code is 1 (S14 fails). Project Gutenberg publishes no PDFs; it is used only as ground-truth text.

<a id="tst-r13"></a>**TST-R13**: Larger quality-metrics corpora (Internet Archive scans paired with Gutenberg texts, a PubMed Central open-access CC BY sample, olmOCR-bench, DocLayNet) are not part of v1 ([roadmap](../worksheets/roadmap.md)). HathiTrust and Google Books bulk downloads and OmniDocBench shall not be used (download restrictions or non-commercial licences).

## 4. OCR accuracy measurement

<a id="tst-r14"></a>**TST-R14**: **Character accuracy** shall be `1 − CER`. CER is the Levenshtein edit distance between the recognised text and the ground truth, divided by the ground truth's length, after both are normalised the same way: Unicode NFC, ligatures expanded, every run of whitespace collapsed to one space, and furniture (headers, footers, page numbers) removed from the ground truth.

<a id="tst-r15"></a>**TST-R15**: Accuracy shall be measured on the synthetic scanned fixtures, page by page, comparing the text pdf2epub puts in the EPUB for that page with the page's ground truth. Pages that fell back to a page image with hidden searchable text are scored on that text and also counted separately. Fallback pages with no hidden text ([OCR-R31](ocr.md#ocr-r31)) are not scored; they are counted and reported as a third figure. The bar is ≥ 98% on the clean set and ≥ 95% on the degraded set ([main](main.md) AC (g)); the thresholds may be tuned once the fixtures exist, by a spec change.

<a id="tst-r16"></a>**TST-R16**: The accuracy measurement shall be a test marked `tesseract`, so it runs in the CI coverage job, and its per-fixture scores shall be printed in the test output.

## 5. CI checks that tie tests to specs

<a id="tst-r17"></a>**TST-R17**: Every test that verifies an acceptance criterion shall carry `@pytest.mark.ac("<ID>")` (one or more IDs; many-to-many). A CI check shall collect every AC ID defined in `docs/specs/` (every HTML anchor whose `id` has the form `<prefix>-ac<N>` or `<prefix>-ac-<letter>`, such as `main-ac-a`) and fail, naming the missing IDs, if any has no marked test and is not on the pending list ([TST-R20](#tst-r20)). Anchors inside Markdown code spans or fenced code blocks are not collected. An AC whose text marks it **manual** is exempt and is confirmed in the v1 acceptance ticket instead. It shall also fail if a marker names an ID that does not exist.

<a id="tst-r20"></a>**TST-R20**: The **pending-AC list** shall be a committed file, `tests/ac_pending.txt`, holding one AC ID per line (blank lines and lines starting with `#` are ignored). It lists the ACs that no build ticket has implemented yet. The marker gate ([TST-R17](#tst-r17)) shall also fail, naming the IDs, if a listed ID has a marked test (it must be removed from the list), if a listed ID does not exist in the specs, or if a listed ID is a **manual** AC. The scaffolding ticket seeds the list with every non-manual AC in `docs/specs/` except its own; each build ticket removes the IDs it implements in the same PR as their marked tests; the v1 acceptance ticket requires the list to be empty.

<a id="tst-r18"></a>**TST-R18**: Tests shall validate every event emitted in their runs against the JSON Schema shipped in the package ([api](api.md)). Any invalid event fails the test.

<a id="tst-r19"></a>**TST-R19**: CI shall run epubcheck on every EPUB that the end-to-end tests write. Any epubcheck error fails the test. Java and epubcheck are CI and dev tools only, never runtime dependencies.

## 6. Acceptance criteria

<a id="tst-ac1"></a>**TST-AC1** (covers [TST-R1](#tst-r1), [TST-R2](#tst-r2)): **Given** a clean checkout, **when** every fixture generator runs twice into two empty folders, **then** the two folders are byte-identical, they match the committed fixtures, every text-based fixture has a ground-truth text file beside it, and importing `pdf2epub` does not import ReportLab.

<a id="tst-ac2"></a>**TST-AC2** (covers [TST-R3](#tst-r3)): **Given** the committed synthetic fixtures, **when** the fixture inventory test runs, **then** each group and fixture listed in TST-R3 exists, and the encrypted fixtures report the expected handler, revision and algorithm when inspected with pypdf (AES-256 R6, RC4-128 R3, owner-only with copy/extract forbidden, owner-only with all permissions, non-Standard filter).

<a id="tst-ac3"></a>**TST-AC3** (covers [TST-R4](#tst-r4)): **Given** the synthetic must-reject fixtures, **when** they convert under `auto`, **then** every one of their text pages is rejected; **and given** the smoke set in the smoke job, **then** no born-digital page and no page of S7 or S9 is rejected.

<a id="tst-ac4"></a>**TST-AC4** (covers [TST-R5](#tst-r5), [TST-R6](#tst-r6), [TST-R7](#tst-r7), [TST-R8](#tst-r8)): **Given** the repository, **when** the provenance test runs, **then** every file under `tests/fixtures/public-domain/` has a PROVENANCE.md row with a URL, a public-domain basis, a matching SHA-256 and a page range; the folder totals ≤ 30 MB; no file is an LFS pointer; and no PDF anywhere under `tests/` is listed in the smoke manifest except by URL.

<a id="tst-ac5"></a>**TST-AC5** (covers [TST-R9](#tst-r9), [TST-R12](#tst-r12)): **Given** `tests/corpus/smoke.toml`, **when** it is parsed, **then** it has exactly the 15 entries S1–S15, each with `id`, `url` (or `derived`), `sha256` (or `derived`), `license` and `expect`, the hashes match the table in TST-R12, and the `password` field is `view` for S10, `master` for S11 and `openpassword` for S12, and absent for every other entry.

<a id="tst-ac6"></a>**TST-AC6** (covers [TST-R10](#tst-r10)): **Given** a loopback HTTP server (bound to 127.0.0.1 and started by the test itself) serving two manifest files, one of which has changed since it was pinned, and a third URL that refuses connections, **when** `scripts/smoke.py` runs, **then** the matching file is cached and converted, the changed file is reported as "upstream file changed" and skipped, the unreachable file is reported and skipped, and a second run downloads nothing.

<a id="tst-ac7"></a>**TST-AC7** (covers [TST-R11](#tst-r11)): **Given** the CI workflow definitions, **when** they are inspected, **then** the smoke workflow is triggered only by `workflow_dispatch`, and it is not listed among the checks the PR workflow runs.

<a id="tst-ac8"></a>**TST-AC8** (covers [TST-R13](#tst-r13)): **Given** the smoke manifest, **when** it is inspected, **then** no URL is on `hathitrust.org`, `books.google.com` or the OmniDocBench dataset.

<a id="tst-ac9"></a>**TST-AC9** (covers [TST-R14](#tst-r14)): **Given** ground truth "ﬁne  day\nend" and recognised text "fine day end", **when** character accuracy is computed, **then** it is 1.0; **and given** ground truth "abcdefghij" and recognised "abcdefghiX", **then** it is 0.9.

<a id="tst-ac10"></a>**TST-AC10** (covers [TST-R15](#tst-r15), [TST-R16](#tst-r16)): **Given** real Tesseract and the synthetic scanned fixtures, **when** the accuracy test runs, **then** the clean set scores ≥ 0.98, the degraded set ≥ 0.95, each fixture's score is printed, and fallback pages are counted in a separate figure.

<a id="tst-ac11"></a>**TST-AC11** (covers [TST-R17](#tst-r17)): In every case below the pending-AC list is empty. **Given** a temporary spec folder whose spec has an AC anchor with id `xyz-ac1` that no test marks, **when** the marker gate runs over that folder, **then** it fails and names `XYZ-AC1`; **given** a test marked `ac("XYZ-AC99")` with no such anchor, **then** it fails and names that ID; **given** an AC anchor with id `xyz-ac-b` that no test marks, **then** it fails and names `XYZ-AC-B`; **given** an AC anchor that appears only inside a code span or a fenced code block, **then** it is not collected; **given** an unmarked AC whose text says it is **manual**, **then** it is not reported; **given** every other AC marked, **then** it passes.

<a id="tst-ac12"></a>**TST-AC12** (covers [TST-R18](#tst-r18)): **Given** a test run in which a sink receives an event missing its `v` field, **when** schema validation runs, **then** the test fails and reports the event type and the missing field.

<a id="tst-ac13"></a>**TST-AC13** (covers [TST-R19](#tst-r19)): **Given** an end-to-end test that writes an EPUB with a deliberately broken manifest entry, **when** epubcheck runs, **then** the test fails with epubcheck's error; **and given** a valid EPUB, it passes.

<a id="tst-ac14"></a>**TST-AC14** (covers [TST-R17](#tst-r17), [TST-R20](#tst-r20)): **Given** a temporary spec folder with ACs `XYZ-AC1`, `XYZ-AC2` and `XYZ-AC3` (manual), a test marked `ac("XYZ-AC1")`, and a pending list, **when** the marker gate runs:
- with the list holding `XYZ-AC2`, **then** it passes;
- with an empty list, **then** it fails and names `XYZ-AC2` as unmarked and not pending;
- with the list holding `XYZ-AC1` and `XYZ-AC2`, **then** it fails and names `XYZ-AC1` as pending but already marked;
- with the list holding `XYZ-AC2` and `XYZ-AC9`, **then** it fails and names `XYZ-AC9` as unknown;
- with the list holding `XYZ-AC2` and `XYZ-AC3`, **then** it fails and names `XYZ-AC3` as manual.

## Open points

The owner accepted points OP54–OP57 in [#51](https://github.com/Bezoar/pdf2epub/issues/51) on 2026-10-14 (numbered as in that review).

- **OP54** Manifest path `tests/corpus/smoke.toml` and cache default `~/.cache/pdf2epub-corpus/` follow the corpora research; any other location works if the plan's fixture table says so.
- **OP55** S15 may be repairable or not depending on the parser; its `expect` accepts either `corrupt_pdf` failure or `repaired_pdf` conversion until the build pins it.
- **OP56** The non-Standard-handler fixture in [TST-R3](#tst-r3) is a synthetic PDF whose Encrypt dictionary names a vendor filter; it contains no vendor DRM code and needs none.
- **OP57** [TST-R15](#tst-r15)'s per-page text comparison assumes the EPUB keeps page-break markers so text can be split back into pages ([epub](epub.md)).
