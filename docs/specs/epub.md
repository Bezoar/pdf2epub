# EPUB

**Status:** draft · **Depends on:** [main](main.md), [api](api.md), [reflow](reflow.md), [batch](batch.md) · **Decisions:** [MIT-compatible PDF library stack](https://github.com/Bezoar/pdf2epub/issues/2), [v1 scope cut and roadmap contents](https://github.com/Bezoar/pdf2epub/issues/6), [Password and decryption UX](https://github.com/Bezoar/pdf2epub/issues/8), [Spec breakdown into main and satellite specs](https://github.com/Bezoar/pdf2epub/issues/14), [ADR 0001](../adr/0001-python-core.md)

This spec owns pdf2epub's own EPUB 3 writer: the container layout, package document, navigation, chapter XHTML and stylesheet, page-image fallback markup, image and cover handling, metadata, deterministic output, and validation. It renders only from the document model defined in [reflow](reflow.md#rfl-r34).

It does not own:
- where the file goes, or atomic replacement ([batch](batch.md));
- how the model is built ([reflow](reflow.md)).

Fixed-layout output and an accessibility audit are [roadmap](../worksheets/roadmap.md) items.

## 1. Writer and container

<a id="epub-r1"></a>**EPUB-R1**: The core shall write EPUB files with its own writer, built on the standard library's `zipfile`, lxml and Jinja2. It shall not use ebooklib, PyMuPDF or any other AGPL- or GPL-licensed library.

<a id="epub-r2"></a>**EPUB-R2**: Each EPUB shall be an EPUB 3.3 container:
- `mimetype` is the first entry, stored uncompressed, with content `application/epub+zip`;
- then `META-INF/container.xml`, pointing to the package document `OEBPS/content.opf`;
- all other entries are compressed with deflate.

<a id="epub-r3"></a>**EPUB-R3**: The EPUB shall never be encrypted or carry DRM. It shall contain no record of:
- any password or password source;
- the source PDF's permission flags;
- OCR engine details.

## 2. Package and navigation

<a id="epub-r4"></a>**EPUB-R4**: The package document shall list every content file, image and stylesheet in its manifest, with correct media types. The spine shall be, in order:
1. the cover page (if any);
2. the navigation document (non-linear);
3. the chapters, in document order.

<a id="epub-r5"></a>**EPUB-R5**: The navigation document `nav.xhtml` shall contain:
- a `toc` nav mirroring the document model's TOC tree, with each entry linking to its chapter file and anchor;
- a `page-list` nav with one entry per `PageBreak` marker, linking to its ID ([EPUB-R19](#epub-r19)) and labelled with its page label;
- a `landmarks` nav with `cover` (if any), `toc` and `bodymatter` (the first chapter after front matter).

<a id="epub-r6"></a>**EPUB-R6**: The EPUB shall also contain an EPUB 2 `toc.ncx` with the same TOC tree and page list, referenced from the spine's `toc` attribute, for older readers.

## 3. Content documents

<a id="epub-r7"></a>**EPUB-R7**: Each chapter of the document model shall be one or more consecutive XHTML5 files: one file, unless [EPUB-R8](#epub-r8) splits it. Its markup is semantic:

| Model | Markup |
|---|---|
| `Heading` | `<h1>`–`<h6>`, with its anchor as `id` |
| `Paragraph` | `<p>` |
| Bold and italic inlines | `<b>` and `<i>` |
| `Image` | `<figure>` with `<img>`, plus a `<figcaption>` when there is a caption |
| `PageBreak` | `<span epub:type="pagebreak" role="doc-pagebreak" id="page-<page>" aria-label="<label>"/>`, inside the `<p>` when the marker is an inline, otherwise between blocks |

The `<html>` element carries `lang` and `xml:lang` set to the book language.

<a id="epub-r8"></a>**EPUB-R8**: A chapter file larger than about 300 KB shall be split into consecutive files at paragraph boundaries. The split is invisible in the TOC: the chapter entry links to the first part.

<a id="epub-r9"></a>**EPUB-R9**: A `PageImage` block shall be rendered as a full-width `<figure>` holding:
- the page image, with `alt` text `Page <label>`;
- a visually hidden element containing the page's searchable text, so the text can still be searched and read aloud while only the image shows.

<a id="epub-r10"></a>**EPUB-R10**: One default stylesheet shall be linked from every content document. It uses only relative units (`em`, `%`), sets no font families and no text or background colours, and so leaves reader settings (font, size, night mode) in control. It also styles full-width figures and visually hidden text.

<a id="epub-r11"></a>**EPUB-R11**: Every `<img>` shall have a non-empty `alt`:
- the caption text if there is one;
- otherwise `Figure <n>` (numbered within the book);
- `Page <label>` for page images;
- `Cover` for the cover.

## 4. Cover

<a id="epub-r12"></a>**EPUB-R12**: When the model has a cover, the EPUB shall include:
- the cover image, with the manifest property `cover-image`;
- a cover XHTML page showing it, first in the spine.

With no cover, neither is present.

## 5. Metadata

<a id="epub-r13"></a>**EPUB-R13**: The package metadata shall contain:
- `dc:title` (the model's title);
- one `dc:creator` for each author, in order;
- `dc:language` (the book language);
- `dc:identifier`, the unique identifier: `urn:uuid:` plus a UUIDv5 derived from the SHA-256 of the source PDF's bytes, under a fixed pdf2epub namespace UUID;
- `dcterms:modified`.

<a id="epub-r14"></a>**EPUB-R14**: `dcterms:modified` shall be deterministic: the PDF's modification date if present, else its creation date, else `1980-01-01T00:00:00Z`. It is formatted as `CCYY-MM-DDThh:mm:ssZ` in UTC.

## 6. Deterministic output

<a id="epub-r15"></a>**EPUB-R15**: Converting the same source PDF bytes, under the same file name (it can supply title and author, [reflow](reflow.md)), with the same options and the same pdf2epub version shall produce a byte-identical EPUB. To achieve this:
- zip entries are in a fixed, sorted order (with `mimetype` first);
- every entry has the timestamp `1980-01-01 00:00:00`;
- the compression level is fixed;
- generated ids and file names are derived from document order, never from time or randomness.

## 7. Validation and write failures

<a id="epub-r16"></a>**EPUB-R16**: Before writing, the writer shall always run built-in checks:
- every XHTML file is well-formed;
- every manifest item exists, and every packaged file is in the manifest, except the container entries `mimetype` and `META-INF/container.xml`, which by definition are not manifest items;
- every internal link and anchor resolves;
- the spine is not empty.

A failed check is a bug: the conversion fails with [`internal_error`](api.md#code-internal_error), and nothing is written.

<a id="epub-r17"></a>**EPUB-R17**: Every EPUB the core produces shall pass epubcheck with zero errors. The test suite and CI enforce this ([testing](testing.md)). epubcheck is a test-time tool, not a runtime dependency.

<a id="epub-r18"></a>**EPUB-R18**: If the EPUB can't be written (for example because of permissions, a full disk or a missing folder), the conversion shall fail with [`write_failed`](api.md#code-write_failed), naming the path and the operating-system reason. [batch](batch.md) guarantees no partial file is left behind.

## 8. Acceptance criteria

<a id="epub-ac1"></a>**EPUB-AC1** (covers [EPUB-R2](#epub-r2), [EPUB-R4](#epub-r4), [EPUB-R17](#epub-r17)): **Given** the synthetic novel fixture, **when** it is converted, **then**:
- the EPUB's first zip entry is `mimetype`, stored uncompressed, containing exactly `application/epub+zip`;
- `META-INF/container.xml` points to `OEBPS/content.opf`;
- epubcheck reports zero errors.

<a id="epub-ac2"></a>**EPUB-AC2** (covers [EPUB-R1](#epub-r1)): **Given** the installed package's dependency metadata, **when** it is inspected, **then** neither `ebooklib` nor `PyMuPDF` (or `fitz`) is a runtime dependency.

<a id="epub-ac3"></a>**EPUB-AC3** (covers [EPUB-R3](#epub-r3)): **Given** the AES-256 user-password fixture, converted with the correct password from `PDF2EPUB_PASSWORD`, and the owner-restricted fixture, converted with its owner password, **when** each EPUB is read back, **then**:
- neither has `META-INF/encryption.xml` or `rights.xml`;
- no entry contains the password string, the words `env` or `owner password`, or the PDF's `/P` value;
- the OPF contains no OCR engine name.

<a id="epub-ac4"></a>**EPUB-AC4** (covers [EPUB-R5](#epub-r5), [EPUB-R6](#epub-r6)): **Given** the novel fixture with a 10-chapter outline and page labels `1`–`40`, **when** it is converted, **then**:
- `nav.xhtml` has a `toc` nav with 10 entries whose `href`s resolve;
- it has a `page-list` with 40 entries labelled `1`…`40`;
- it has `landmarks` with `toc` and `bodymatter`;
- `toc.ncx` has 10 navPoints and 40 pageTargets.

<a id="epub-ac5"></a>**EPUB-AC5** (covers [EPUB-R7](#epub-r7), [EPUB-R11](#epub-r11)): **Given** a fixture with level-1 and level-2 headings, bold and italic words, a captioned figure, an uncaptioned figure and page labels, **when** it is converted, **then** the chapter XHTML contains:
- `<h1>`, `<h2>`, `<b>` and `<i>`;
- a `<figure>` with `<figcaption>` whose `<img alt>` equals the caption;
- an `<img alt="Figure 2">`;
- `pagebreak` spans with matching `aria-label`s;
- `lang` set on `<html>`.

<a id="epub-ac6"></a>**EPUB-AC6** (covers [EPUB-R8](#epub-r8)): **Given** a fixture whose single chapter holds about 900 KB of text, **when** it is converted, **then**:
- that chapter is split into at least 3 XHTML files, each at most about 300 KB;
- each file starts at a paragraph boundary;
- the TOC has one entry for the chapter, pointing to the first part.

<a id="epub-ac7"></a>**EPUB-AC7** (covers [EPUB-R9](#epub-r9), [EPUB-R10](#epub-r10)): **Given** the two-column fixture, whose pages become page images, **when** it is converted, **then**:
- each such page is a `<figure>` with an `<img alt="Page <label>">` and a hidden element containing that page's text (a distinctive sentence from the page is found in it);
- the stylesheet contains no `px`/`pt` font sizes, no `font-family` and no `color`/`background-color` declarations.

<a id="epub-ac8"></a>**EPUB-AC8** (covers [EPUB-R12](#epub-r12)):
- **Given** default options, **then** the manifest has exactly one item with property `cover-image`, and the spine starts with a cover page showing it.
- **Given** `cover = None`, **then** there is no `cover-image` item and no cover page.

<a id="epub-ac9"></a>**EPUB-AC9** (covers [EPUB-R13](#epub-r13), [EPUB-R14](#epub-r14)): **Given** the fixture `Jane Doe - A Book.pdf` with Info `/ModDate (D:20200102030405Z)` and two author overrides `A` and `B`, **when** it is converted, **then** the OPF has:
- `dc:creator` `A` then `B`;
- `dc:language`;
- `dc:identifier` equal to `urn:uuid:` plus the UUIDv5 of the file's SHA-256 under the pdf2epub namespace;
- `dcterms:modified` `2020-01-02T03:04:05Z`.

**Given** a PDF with no dates, **then** `dcterms:modified` is `1980-01-01T00:00:00Z`.

<a id="epub-ac10"></a>**EPUB-AC10** (covers [EPUB-R15](#epub-r15)): **Given** the novel fixture, **when** it is converted twice, into two different folders and at different times, **then** the two EPUBs are byte-identical, and every zip entry's timestamp is 1980-01-01 00:00:00.

<a id="epub-ac11"></a>**EPUB-AC11** (covers [EPUB-R16](#epub-r16)): **Given** a document model in which a TOC entry points to a missing anchor (injected through the writer's test seam), **when** the writer runs, **then**:
- the conversion is `failed` with [`internal_error`](api.md#code-internal_error);
- no EPUB and no temp file remain.

<a id="epub-ac12"></a>**EPUB-AC12** (covers [EPUB-R18](#epub-r18)): **Given** an output folder without write permission, **when** the novel fixture is converted into it, **then**:
- the conversion is `failed` with [`write_failed`](api.md#code-write_failed) (error), whose message names the destination path;
- the exit code is 1.

<a id="epub-r19"></a>**EPUB-R19**: Page-break IDs shall be built from the PDF page index only (`page-<page>`), never from the page label, so every ID is a valid, unique XML ID whatever the labels are. Labels may repeat or contain any characters. They appear only as escaped text and attribute values (`aria-label`, page-list and `toc.ncx` entries).

<a id="epub-ac13"></a>**EPUB-AC13** (covers [EPUB-R19](#epub-r19), [EPUB-R5](#epub-r5)): **Given** a fixture whose pages 1–4 have the labels `i`, `i`, `A&B 1` and `<2>`, **when** it is converted, **then**:
- the page-break spans have the IDs `page-1` … `page-4`, all distinct;
- their `aria-label`s read `i`, `i`, `A&B 1` and `<2>` once unescaped;
- the `page-list` has 4 entries with those labels, linking to `#page-1` … `#page-4`;
- epubcheck reports zero errors.

## Open points

- `dcterms:modified` is derived from the PDF's dates so output is deterministic, rather than using the conversion time.
- The UUIDv5 namespace UUID for `dc:identifier` is to be generated once and fixed in the code; it is not chosen here.
- The ~300 KB split threshold is carried over from the archived spec.
- How visually hidden searchable text is styled (for example off-screen clipping) is left to the build. Reader support varies, so the PR should check Apple Books and Calibre.
- JPEG quality 85 and the 1600 px long edge are owned by [reflow](reflow.md#rfl-r27). The writer embeds images exactly as given.
- A failed built-in check is treated as `internal_error`, not a new issue code.
