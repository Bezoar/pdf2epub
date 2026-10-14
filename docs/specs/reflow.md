# Reflow

**Status:** draft · **Depends on:** [main](main.md), [api](api.md), [ocr](ocr.md), [epub](epub.md) · **Decisions:** [MIT-compatible PDF library stack](https://github.com/Bezoar/pdf2epub/issues/2), [v1 scope cut and roadmap contents](https://github.com/Bezoar/pdf2epub/issues/6), [OCR engine interface design](https://github.com/Bezoar/pdf2epub/issues/13), [Spec breakdown into main and satellite specs](https://github.com/Bezoar/pdf2epub/issues/14), [Text-layer quality check](https://github.com/Bezoar/pdf2epub/issues/15), [ADR 0001](../adr/0001-python-core.md)

This spec owns how one opened PDF becomes a structured book: parsing and its failures, text extraction, layout analysis, furniture removal, page joins, de-hyphenation, headings and inline styling, page-image fallback for complex and multi-column pages, chapters and the table of contents, page-break markers, metadata, images and the cover, and page sequence gaps. Its output is the **document model** handed to the EPUB writer.

It does not own:
- decryption and access classification ([passwords](passwords.md));
- which pages are OCR'd, the text-layer quality check, and OCR-driven fallbacks ([ocr](ocr.md));
- EPUB markup and packaging ([epub](epub.md));
- where the EPUB is written ([batch](batch.md)).

Footnotes, tables and math as content, fixed layout, multi-column reading order, page ranges, title-page metadata heuristics, ISBN detection and language auto-detection are all [roadmap](../worksheets/roadmap.md) items.

## 1. Opening and parsing

<a id="rfl-r1"></a>**RFL-R1**: The core shall parse PDFs with pypdfium2 (rendering, outline, page labels, metadata, per-character font, size and bounding box) and pdfminer.six (layout grouping). It shall use no other PDF parser at runtime, except pypdf for the owner/user password distinction owned by [passwords](passwords.md).

<a id="rfl-r2"></a>**RFL-R2**: When the document can't be parsed at all, even with the parser's repair, the conversion shall fail with [`corrupt_pdf`](api.md#code-corrupt_pdf), and no EPUB shall be written.

<a id="rfl-r3"></a>**RFL-R3**: When the parser opens the document only by recovering from damage (for example a rebuilt cross-reference table or a truncated file), the conversion shall continue and record [`repaired_pdf`](api.md#code-repaired_pdf).

<a id="rfl-r4"></a>**RFL-R4**: A document with zero pages shall fail with [`empty_document`](api.md#code-empty_document).

<a id="rfl-r35"></a>**RFL-R35**: A document that has pages but none of whose pages yields any content shall also fail with [`empty_document`](api.md#code-empty_document), and no EPUB shall be written. A page yields content if its text (from its text layer or from OCR, after normalisation and before furniture removal) has at least one non-whitespace character, or if the document model gets any image from it: a book image kept under [RFL-R26](#rfl-r26), a page-image fallback, or a scanned page's rendered image kept under [OCR-R17](ocr.md#ocr-r17). This is the registry's "no page yields any text or image"; whether an image counts is decided by those rules, not by a separate significance test. Blank pages are still handled page by page as [OCR-R1](ocr.md#ocr-r1) and [OCR-R17](ocr.md#ocr-r17) say (no OCR, no page-level issue); `empty_document` is a document-level failure raised only when every page is like that, whatever `OcrOptions.mode` is.

<a id="rfl-r5"></a>**RFL-R5**: The core shall treat every PDF as untrusted:
- it never executes embedded JavaScript or actions;
- it never fetches external resources or opens a network connection;
- it never follows links to other files.

<a id="rfl-r6"></a>**RFL-R6**: The core shall enforce resource limits on decoded content, in particular a maximum decoded pixel count for any single image or page render, and a maximum decompressed stream size. When a limit is hit, the conversion shall fail with [`resource_limit`](api.md#code-resource_limit), naming the limit that was hit and the page, and the batch shall continue. The limits are internal constants.

## 2. Extraction

<a id="rfl-r7"></a>**RFL-R7**: For each page whose text comes from its text layer, the core shall extract **spans**: text, bounding box, font name, font size and bold/italic flags. For pages whose text comes from OCR, it shall build spans from the OCR result's words and lines ([ocr](ocr.md#ocr-r1) decides which source a page uses). OCR spans carry a size estimated from line height and no bold/italic.

<a id="rfl-r8"></a>**RFL-R8**: Extracted text shall be normalised:
- to Unicode NFC;
- with typographic ligatures expanded (`ﬁ` → `fi`, `ﬂ` → `fl`, `ﬀ` → `ff`, `ﬃ` → `ffi`, `ﬄ` → `ffl`);
- with soft hyphens (U+00AD) removed from the text, while still marking a line-end break as a word break for de-hyphenation ([RFL-R17](#rfl-r17)).

Normalisation applies equally to OCR'd text.

<a id="rfl-r9"></a>**RFL-R9**: The core shall extract embedded raster images with their bounding boxes, for use as book images ([§8](#8-images-and-cover)).

## 3. Layout analysis

<a id="rfl-r10"></a>**RFL-R10**: Per page, the core shall group spans into lines and lines into blocks using geometry: baseline, line spacing and horizontal gaps. Within a single-column page, the reading order is top to bottom.

<a id="rfl-r11"></a>**RFL-R11**: The core shall detect pages with more than one text column (for example from an x-projection histogram of text). Such a page shall become a page-image fallback with [`page_fallback`](api.md#code-page_fallback) reason `multi_column`. Text from two columns shall **never** be interleaved in the output. This rule applies to both typeset and OCR'd pages, and in both `mode` values ([RFL-R14](#rfl-r14)).

<a id="rfl-r12"></a>**RFL-R12**: Each block on a reflowed page shall be classified as one of:
- `heading` (with a level from 1 to 6);
- `paragraph`;
- `image` (with an optional caption: the adjacent short block in smaller type directly below or above it);
- `furniture` ([§4](#4-furniture)).

Lists and block quotes are emitted as paragraphs in v1. Verse, code and other text whose line breaks carry meaning is a **line block** ([RFL-R36](#rfl-r36)).

<a id="rfl-r36"></a>**RFL-R36**: A text block shall be classified as a **line block**, a block whose line breaks carry meaning (verse, song lyrics, addresses, code), when either:
- every line of the block is set in a monospace font; or
- it has at least 3 lines, most of them end well short of the column's right edge (ragged right), where prose lines run to it, and none of them ends in a word broken with a hyphen or a soft hyphen, as only wrapped prose does.

Line blocks are detected from geometry and fonts only; the exact thresholds are internal constants calibrated on fixtures. A line block keeps its lines as they are in the source: it is exempt from line joining ([RFL-R19](#rfl-r19)), from line-end de-hyphenation ([RFL-R17](#rfl-r17)) and from page joining ([RFL-R18](#rfl-r18)), in both directions. A monospace line block also keeps the spaces in its lines, including leading spaces, which are counted from the text layer and from each line's start relative to the block's leftmost line. Line blocks are not detected on page-image fallback pages; their hidden text is unchanged.

<a id="rfl-r13"></a>**RFL-R13**: The core shall compute a **page complexity** score from:
- the fraction of the page area covered by images or vector graphics;
- table-like ruling or grid density;
- the ratio of mathematical glyphs;
- the ratio of blocks it could not classify.

In `mode = "auto"`, a page whose score is above an internal threshold shall become a page-image fallback with [`page_fallback`](api.md#code-page_fallback) reason `complex`.

<a id="rfl-r14"></a>**RFL-R14**: `ConversionOptions.mode` shall take `"auto"` (default) or `"reflow"`. `"reflow"` disables the `complex` fallback only. Multi-column fallback ([RFL-R11](#rfl-r11)) and OCR-driven fallbacks ([ocr](ocr.md)) still apply.

<a id="rfl-r15"></a>**RFL-R15**: A page-image fallback page shall be carried in the document model as a **page image**:
- a render of the whole page (the un-cleaned render for scanned pages), downscaled to the image size limit ([RFL-R27](#rfl-r27));
- its searchable text: the page's own text for `complex` and `multi_column` pages, in column order: every line of one column, top to bottom, before any line of the next column, columns left to right. Lines from different columns shall never be interleaved, in the hidden text any more than in visible text. On any page detected as multi-column ([RFL-R11](#rfl-r11)), this column order applies whatever the text's source: OCR words are assigned to the columns found by RFL-R11 and emitted column by column, even though OCR itself treats the page as one column ([ocr](ocr.md#ocr-r28)). For OCR-driven fallbacks, the text chosen by [ocr](ocr.md).

The page image sits in reading order where the page was. [epub](epub.md#epub-r9) defines its markup.

## 4. Furniture

<a id="rfl-r16"></a>**RFL-R16**: The core shall remove **furniture**: running headers, running footers and page numbers. It finds them by comparing the top and bottom bands of pages across the document. A block is furniture when either:
- its text repeats (allowing for a changing number) at a consistent position on many pages; or
- it matches a page-number pattern (arabic or roman numerals, optionally with decoration such as `— 12 —`) at a consistent position.

Removal applies to typeset and OCR'd pages alike. Detected page numbers are kept as data for page sequence gaps ([§9](#9-page-sequence-gaps)).

## 5. Page joins and de-hyphenation

<a id="rfl-r17"></a>**RFL-R17**: A word broken across lines or pages with a hyphen (`exam-` / `ple`) shall be joined without the hyphen when either:
- the joined word is in the language's wordlist; or
- the break was a soft hyphen.

Otherwise the hyphen shall be kept and the parts joined (`well-known`). When the language has no wordlist, only soft-hyphen breaks are joined without the hyphen. This wordlist is the one the text-layer quality check uses ([ocr](ocr.md)).

<a id="rfl-r18"></a>**RFL-R18**: A paragraph that ends a reflowed page without terminal punctuation shall be joined to the first paragraph of the next reflowed page when that paragraph starts with a lowercase letter or other continuation (no indent and no heading). Furniture is removed before this test. Joining also skips over images that sit between the two paragraphs: the image is placed after the joined paragraph. A join never crosses a page-image fallback page.

<a id="rfl-r19"></a>**RFL-R19**: Lines within a paragraph shall be joined with a single space. Lines in Chinese and Japanese (Han, Hiragana and Katakana, and CJK punctuation) are joined with no space. Korean (Hangul) separates words with spaces, so its lines are joined with a single space, like Latin text.

## 6. Headings and inline styling

<a id="rfl-r20"></a>**RFL-R20**: For typeset text, the body size shall be the most common span size, weighted by character count. A block is a heading when:
- it is larger or bolder than body text;
- it is short (at most about two lines);
- it is set apart by vertical space.

Heading levels are assigned by clustering the distinct heading styles, largest first, capped at 6.

<a id="rfl-r21"></a>**RFL-R21**: For OCR'd text, headings shall be inferred from line height and position alone (taller lines that are set apart and centred or at the top of the page). OCR'd text has no bold/italic detection in v1.

<a id="rfl-r22"></a>**RFL-R22**: For typeset text, runs of bold and italic, taken from font flags and font-name style suffixes, shall become inline bold and italic marks.

## 7. Chapters, table of contents and page labels

<a id="rfl-r23"></a>**RFL-R23**: Chapters shall come from the PDF outline when it has at least 3 entries that resolve to pages. Each **top-level** entry starts a chapter at the first block at or after its destination. Nested entries do not start chapters: they become nested TOC entries linking to an anchor inside their parent chapter. Outline titles are used as TOC labels.

<a id="rfl-r24"></a>**RFL-R24**: Otherwise chapters shall come from detected headings. Every level-1 heading starts a chapter, and so does any heading that matches a chapter pattern:
- `Chapter 7`, `CHAPTER SEVEN`, `Chapter VII`;
- `Part II`;
- `Prologue`, `Epilogue`.

Matching is case-insensitive, and number words cover one to one hundred. Lower heading levels become nested TOC entries. Content before the first chapter forms a front-matter chapter with no TOC entry.

<a id="rfl-r25"></a>**RFL-R25**: The core shall record a page-break marker at the start of every PDF page's content, labelled with the page's PDF page label. A page with no label uses its 1-based page index.

## 8. Images and cover

<a id="rfl-r26"></a>**RFL-R26**: Book images ([RFL-R9](#rfl-r9)) shall be kept in reading order at their block position. Identical images (same decoded-pixel hash) shall be stored once and referenced wherever they appear.

<a id="rfl-r27"></a>**RFL-R27**: Every image, including page images and the cover, shall be:
- downscaled so its long edge is at most 1600 px;
- re-encoded as JPEG (quality 85) when photographic, or PNG when it is line art or has few colours or transparency.

<a id="rfl-r28"></a>**RFL-R28**: `ConversionOptions.cover` shall be `"page1"` (default: a render of page 1), a path to an image file, or `None` (no cover). A cover path that can't be read or decoded is a usage error, reported before the batch starts.

## 9. Page sequence gaps

<a id="rfl-r29"></a>**RFL-R29**: Using the printed page numbers detected by furniture removal ([RFL-R16](#rfl-r16)), the core shall find breaks inside a run of arabic page numbers: a number missing, or a number repeated. Each break is recorded as [`page_sequence_gap`](api.md#code-page_sequence_gap), naming:
- the PDF pages on either side;
- the missing or repeated printed numbers.

It applies to born-digital and scanned PDFs.

<a id="rfl-r30"></a>**RFL-R30**: A page sequence gap shall **not** be reported for:
- roman-numeral front matter, or the switch from roman to arabic numbering;
- pages without a detected number (unnumbered chapter openers, plates, blank pages) when the numbering resumes at the value that accounts for them;
- a run of fewer than 5 consecutive numbered pages.

It fires only on a clear break.

## 10. Metadata and language

<a id="rfl-r31"></a>**RFL-R31**: Each metadata field shall be taken from the first of these sources that supplies it:
1. `ConversionOptions` overrides (`title`, `authors`, `language`);
2. XMP metadata;
3. the Info dictionary;
4. for title and authors only, the filename pattern `Author - Title.pdf` (authors may be split on ` & ` and `, `);
5. for the title only, the filename stem as a last resort.

<a id="rfl-r32"></a>**RFL-R32**: The book language shall be:
1. `ConversionOptions.language` (a BCP 47 tag) if given;
2. otherwise the PDF's declared language (catalog `/Lang`, or XMP `dc:language`);
3. otherwise `en`, recording [`language_defaulted`](api.md#code-language_defaulted).

<a id="rfl-r33"></a>**RFL-R33**: `ConversionOptions` fields owned here, with their defaults:

| Field | Meaning | Default |
|---|---|---|
| `mode` | `"auto"` or `"reflow"` ([RFL-R14](#rfl-r14)) | `"auto"` |
| `language` | BCP 47 book language override | `None` |
| `title` | Title override | `None` |
| `authors` | Author override, an ordered list | `None` |
| `cover` | `"page1"`, a path, or `None` ([RFL-R28](#rfl-r28)) | `"page1"` |

## 11. Document model

<a id="rfl-r34"></a>**RFL-R34**: The output of reflow shall be a document model that holds no PDF objects:
- `Document`:
  - `metadata` (title, authors, language);
  - `cover` (image or none);
  - `chapters`;
  - `toc` (a tree of label → chapter/anchor);
  - `images` (deduplicated assets).
- `Chapter`: a title (or none, for front matter) and its `blocks`.
- `Block`: one of
  - `Heading{level, inlines, anchor}`;
  - `Paragraph{inlines}`;
  - `LineBlock{lines, monospace}`: a line block ([RFL-R36](#rfl-r36)); each line is a list of inlines, and `monospace` is true when the block is set wholly in a monospace font;
  - `Image{asset, caption}`;
  - `PageImage{asset, text, page}`;
  - `PageBreak{label, page}`, when a page boundary falls between blocks.
- `Inline`: one of
  - `Text{str, bold, italic}`;
  - `PageBreak{label, page}`, when a page boundary falls inside a paragraph joined across pages.

`label` is the printed page label for display; `page` is the 1-based PDF page index and is unique within the book.

The EPUB writer ([epub](epub.md)) renders only from this model.

## 12. Acceptance criteria

<a id="rfl-ac1"></a>**RFL-AC1** (covers [RFL-R1](#rfl-r1), [RFL-R7](#rfl-r7), [RFL-R10](#rfl-r10), [RFL-R12](#rfl-r12), [RFL-R34](#rfl-r34)): **Given** the synthetic single-column novel fixture, **when** it is converted with default options, **then**:
- the outcome is `converted` with no `error` or `warning` issues;
- every body paragraph of the fixture's source text appears in the document model as one `Paragraph`, in source order.

<a id="rfl-ac2"></a>**RFL-AC2** (covers [RFL-R2](#rfl-r2)): **Given** a truncated-beyond-repair fixture (random bytes after a valid `%PDF-` header), **when** it is converted, **then**:
- the outcome is `failed` with [`corrupt_pdf`](api.md#code-corrupt_pdf) (error);
- no EPUB is written.

<a id="rfl-ac3"></a>**RFL-AC3** (covers [RFL-R3](#rfl-r3)): **Given** the novel fixture with its cross-reference table removed, **when** it is converted, **then**:
- the outcome is `converted`;
- the issues include [`repaired_pdf`](api.md#code-repaired_pdf) (warning).

<a id="rfl-ac4"></a>**RFL-AC4** (covers [RFL-R4](#rfl-r4)): **Given** a valid PDF with zero pages, **when** it is converted, **then** the outcome is `failed` with [`empty_document`](api.md#code-empty_document) (error) and no EPUB is written.

<a id="rfl-ac24"></a>**RFL-AC24** (covers [RFL-R35](#rfl-r35)): **Given** a valid born-digital PDF with three pages that have no text and no image, **when** it is converted with each `OcrOptions.mode` (`auto`, `always`, `never`), **then** the outcome is `failed` with [`empty_document`](api.md#code-empty_document) (error), no EPUB is written, the OCR engine is never called, and `empty_document` is the conversion's only issue. **Given** the same PDF with a fourth page holding one line of text, **then** the outcome is `converted` with no issue for the three blank pages.

<a id="rfl-ac5"></a>**RFL-AC5** (covers [RFL-R5](#rfl-r5)): **Given** a fixture with document-level JavaScript, an `/OpenAction` launching a URI, and a page with an external image reference, **when** it is converted with network access blocked in the test, **then**:
- no network connection is attempted;
- no script runs;
- the outcome is `converted`.

<a id="rfl-ac6"></a>**RFL-AC6** (covers [RFL-R6](#rfl-r6)): **Given** a fixture whose embedded image declares dimensions above the decoded-pixel limit (a decompression bomb), placed in a batch with the novel fixture, **when** the batch runs, **then**:
- the bomb's conversion is `failed` with [`resource_limit`](api.md#code-resource_limit) (error), naming its page;
- the novel converts;
- peak memory of the worker stays below 1 GB.

<a id="rfl-ac7"></a>**RFL-AC7** (covers [RFL-R8](#rfl-r8)): **Given** a fixture whose text uses the `ﬁ` and `ﬂ` ligatures, decomposed accented letters and a soft hyphen inside a word, **when** it is converted, **then** the output text contains `fi`, `fl`, NFC-composed letters and no U+00AD or ligature code points.

<a id="rfl-ac8"></a>**RFL-AC8** (covers [RFL-R11](#rfl-r11)): **Given** the synthetic two-column fixture, **when** it is converted in `mode = "auto"` and again in `mode = "reflow"`, **then** in both runs:
- every two-column page is a `PageImage` with a [`page_fallback`](api.md#code-page_fallback) issue, reason `multi_column`, listing those pages;
- no `Paragraph` contains text from both columns;
- each of those pages' searchable text holds the whole left column's text before any of the right column's.

**And given** a 300 DPI scanned rendering of the same fixture with real Tesseract, **then** the same two checks hold for its OCR'd hidden text.

<a id="rfl-ac9"></a>**RFL-AC9** (covers [RFL-R13](#rfl-r13), [RFL-R14](#rfl-r14), [RFL-R15](#rfl-r15)): **Given** a fixture with one page holding a ruled table and an equation, and other pages of plain prose, **when** it is converted in `mode = "auto"`, **then**:
- that page is a `PageImage` whose `text` contains the table's cell text;
- a `page_fallback` issue with reason `complex` lists exactly that page;
- the other pages are reflowed.

**When** it is converted in `mode = "reflow"`, **then** no page has reason `complex`.

<a id="rfl-ac10"></a>**RFL-AC10** (covers [RFL-R16](#rfl-r16)): **Given** the novel fixture, with a running header (book title on even pages, chapter title on odd pages) and a centred page number in the footer, **when** it is converted, **then** no `Paragraph` or `Heading` contains the running header text or a bare page number.

<a id="rfl-ac11"></a>**RFL-AC11** (covers [RFL-R17](#rfl-r17)): **Given** an English fixture whose line ends break `exam-`/`ple`, `well-`/`known` and `informa`+soft hyphen/`tion`, **when** it is converted, **then** the text contains `example`, `well-known` and `information`.

**Given** the same layout in a language with no wordlist, **then** only the soft-hyphen word is joined without its hyphen.

<a id="rfl-ac12"></a>**RFL-AC12** (covers [RFL-R18](#rfl-r18), [RFL-R19](#rfl-r19)): **Given** the novel fixture, in which a sentence runs across a page break and the next page starts in lowercase, **when** it is converted, **then**:
- that sentence is in a single `Paragraph`;
- a `PageBreak` **inline** sits inside that `Paragraph`'s inlines, at the join point;
- a paragraph that ends with a full stop at a page end is not joined to the next page's indented paragraph.

<a id="rfl-ac13"></a>**RFL-AC13** (covers [RFL-R20](#rfl-r20), [RFL-R22](#rfl-r22)): **Given** a typeset fixture with 24 pt chapter titles, 14 pt bold section titles, 11 pt body text and italic and bold words in the body, **when** it is converted, **then**:
- chapter titles are `Heading` level 1 and section titles are level 2;
- the italic and bold words carry the matching inline marks.

<a id="rfl-ac14"></a>**RFL-AC14** (covers [RFL-R21](#rfl-r21)): **Given** the clean scanned variant of the multi-chapter fixture, OCR'd through the fake `OcrEngine` returning taller, centred chapter-title lines, **when** it is converted, **then**:
- chapter titles are level-1 headings;
- no inline bold/italic marks exist.

<a id="rfl-ac15"></a>**RFL-AC15** (covers [RFL-R23](#rfl-r23)): **Given** the novel fixture with a 12-entry outline (10 chapters, 2 of them with one nested entry), **when** it is converted, **then**:
- the document has 10 chapters (plus front matter if content precedes the first entry);
- the TOC has 10 top-level entries with the outline titles and 2 nested entries.

<a id="rfl-ac16"></a>**RFL-AC16** (covers [RFL-R24](#rfl-r24)): **Given** the novel fixture with no outline and headings `CHAPTER ONE` … `CHAPTER TEN` in 14 pt body-size bold, **when** it is converted, **then** the TOC has 10 entries labelled with those headings, and each starts a chapter.

**Given** the fixture with an outline of only 2 resolvable entries, **then** detected headings are used instead.

<a id="rfl-ac17"></a>**RFL-AC17** (covers [RFL-R25](#rfl-r25)): **Given** a fixture with page labels `i`–`iv` followed by `1`–`20`, **when** it is converted, **then** the stream holds 24 `PageBreak` markers labelled `i`…`iv`, `1`…`20` in order.

**Given** a fixture with no page labels, **then** the labels are `1`…`N`.

<a id="rfl-ac18"></a>**RFL-AC18** (covers [RFL-R26](#rfl-r26), [RFL-R27](#rfl-r27), [RFL-R9](#rfl-r9)): **Given** a fixture embedding a 4000×3000 photograph on two pages and a 2-colour line drawing, **when** it is converted, **then**:
- the document has exactly 2 image assets;
- the photograph is a JPEG with long edge 1600 px, referenced from 2 `Image` blocks;
- the drawing is a PNG.

<a id="rfl-ac19"></a>**RFL-AC19** (covers [RFL-R28](#rfl-r28)): **Given** the novel fixture:
- **when** it is converted with default options, **then** the cover is a render of page 1;
- **with** `cover = None`, **then** there is no cover;
- **with** `cover` set to a PNG path, **then** that image (downscaled per [RFL-R27](#rfl-r27)) is the cover;
- **with** a path that does not exist, **then** the run is a usage error (exit code 2) and no conversion starts.

<a id="rfl-ac20"></a>**RFL-AC20** (covers [RFL-R29](#rfl-r29)): **Given** a 30-page scanned fixture with printed numbers 1–30 where printed page 17 is missing (PDF page 17 shows 18), **when** it is converted, **then**:
- the issues include [`page_sequence_gap`](api.md#code-page_sequence_gap) (warning), naming PDF pages 16 and 17 and missing printed number 17;
- the outcome is `converted`.

**Given** a fixture where printed page 9 appears twice, **then** the issue names repeated number 9.

<a id="rfl-ac21"></a>**RFL-AC21** (covers [RFL-R30](#rfl-r30)): **Given** a fixture with roman front matter `i`–`x`, then `1`–`40`, an unnumbered chapter-opener page between 12 and 14 (the opener is page 13), and an unnumbered plate between 30 and 31, **when** it is converted, **then** no `page_sequence_gap` issue is reported.

<a id="rfl-ac22"></a>**RFL-AC22** (covers [RFL-R31](#rfl-r31), [RFL-R33](#rfl-r33)): **Given** a fixture named `Jane Doe - A Book.pdf` with no XMP and an Info `/Title` of `Real Title`, **when** it is converted:
- with default options, **then** the title is `Real Title` and the author is `Jane Doe`;
- with `title = "Override"`, **then** the title is `Override`.

**Given** a fixture named `scan0001.pdf` with no metadata, **then** the title is `scan0001` and there is no author.

<a id="rfl-ac23"></a>**RFL-AC23** (covers [RFL-R32](#rfl-r32)): **Given** a fixture with no `/Lang` and no XMP language:
- **when** it is converted with default options, **then** the language is `en` and the issues include [`language_defaulted`](api.md#code-language_defaulted) (warning);
- **with** `language = "de"`, **then** the language is `de` with no such issue.

**Given** a fixture with `/Lang (fr)`, **then** the language is `fr` with no such issue.

<a id="rfl-ac25"></a>**RFL-AC25** (covers [RFL-R36](#rfl-r36), [RFL-R34](#rfl-r34)): **Given** the born-digital verse-and-code fixture, whose first page holds a three-stanza poem between two prose paragraphs, **when** it is converted, **then**:
- each stanza is one `LineBlock`, not `monospace`, whose lines match the stanza's source lines, in order;
- the two prose paragraphs are ordinary `Paragraph`s matching the ground truth.

<a id="rfl-ac26"></a>**RFL-AC26** (covers [RFL-R36](#rfl-r36)): **Given** the born-digital novel fixture, **when** it is converted, **then** the document model holds no `LineBlock` (no false positives on prose, dialogue or short final lines).

<a id="rfl-ac27"></a>**RFL-AC27** (covers [RFL-R36](#rfl-r36), [RFL-R17](#rfl-r17), [RFL-R18](#rfl-r18), [RFL-R19](#rfl-r19)): **Given** the born-digital verse-and-code fixture, whose monospace code block has lines that end in a hyphen and continues on the next page, **when** it is converted, **then**:
- the code is `monospace` `LineBlock`s whose lines match the source lines exactly, leading spaces included;
- no line-end hyphen is removed and no two lines are joined;
- the block ending the first page is not joined to the next page's text: a `PageBreak` block sits between it and the code that continues on the next page.

<a id="rfl-ac28"></a>**RFL-AC28** (covers [RFL-R19](#rfl-r19)): **Given** a born-digital page with a Japanese paragraph and a Korean paragraph, each wrapped over several lines, **when** it is converted, **then** the Japanese lines are joined with no space and the Korean lines with one space.

## Open points

- Assumed `mode = "reflow"` disables only the `complex` fallback. Multi-column pages still fall back, because "never interleave" is absolute.
- Lists and block quotes are rendered as paragraphs in v1, since the scope decision doesn't mention them. _(Owner review in [#51](https://github.com/Bezoar/pdf2epub/issues/51), OP26: changed. The assumption first covered preformatted text too; verse and code are now line blocks ([RFL-R36](#rfl-r36), added by [#52](https://github.com/Bezoar/pdf2epub/issues/52)).)_
- The PDF's declared language (`/Lang` or XMP) is used before defaulting to `en`. The scope decision says "`--language`, else `en`"; using declared metadata is consistent with the metadata precedence and the OCR language order.
- Which wordlists ship in v1 isn't decided. Assumed at least English; other languages get soft-hyphen-only joining.
- Assumed: a page join never crosses a page-image fallback page, and images between two joined paragraphs move after the joined paragraph.
- The printed "Contents" page is kept as ordinary text (the archived spec's drop-it heuristic is not carried over).
- Assumed minimum run length of 5 numbered pages before a page sequence gap can fire; calibrate on fixtures.
- Resource-limit values, complexity threshold and heading-detection tolerances are internal constants to calibrate on fixtures.
- [RFL-R35](#rfl-r35) reads the `empty_document` registry entry ("no page yields any text or image") as a document-level check on top of the per-page blank-page rule. A test of a single blank page that expects no issue (for example [OCR-AC25](ocr.md#ocr-ac25)'s blank scanned page) therefore puts that page in a document with at least one page that yields content.
- A `resource_limit` hit fails the whole conversion (severity error per the registry), rather than degrading only the offending page.
