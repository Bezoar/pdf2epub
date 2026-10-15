# pdf2epub

Converts PDF books (born-digital or scanned) into reflowable EPUB books, one at a time or in batches, for personal reading and backup.

## Language

### Conversions and batches

**Conversion**:
One source PDF turned into one EPUB.
_Avoid_: job, export, transform

**Batch**:
A set of conversions run together, where one failing conversion never stops the others.
_Avoid_: bulk run, queue

**Batch report**:
The summary given at the end of a batch: every conversion's outcome and its issues.
_Avoid_: log, summary file

**Outcome**:
How one conversion ended: converted, skipped or failed.
_Avoid_: result, status

**Skipped**:
The outcome of a conversion deliberately not run, such as when its EPUB already exists. Not a failure.
_Avoid_: ignored, passed

**Severity**:
How serious an issue is: error (the conversion failed), warning or info.
_Avoid_: level, priority

**Issue**:
A named kind of problem attached to one conversion (e.g. missing password, low OCR confidence). An issue may or may not stop that conversion.
_Avoid_: error, warning (as umbrella terms)

**Front end**:
Any interface a person uses to request conversions and see their outcomes. The command line is the first front end.
_Avoid_: client, UI (for the CLI)

### Book structure

**Reflow**:
Turning a PDF's fixed page layout into text that flows to fit any reader's screen.
_Avoid_: re-layout, conversion (for this narrower sense)

**Page-image fallback**:
Embedding a page as a picture of itself, with its text kept searchable, because it could not be reflowed faithfully.
_Avoid_: rasterising, image mode

**Unreadable page**:
A page of a damaged PDF that one parser can't load or doesn't have. It keeps its place in the book with a visible notice and whatever could be recovered of it.
_Avoid_: missing page, lost page

**Furniture**:
Text repeated on printed pages for navigation rather than content: running headers, running footers, page numbers.
_Avoid_: boilerplate, chrome, artifacts

**Line block**:
A block of text whose line breaks carry meaning, such as verse, song lyrics, an address or code, so its lines are kept as they are instead of being joined into a paragraph.
_Avoid_: preformatted text (for verse), poem block

**Text layer**:
The text a PDF page already carries, whether typeset or added by earlier OCR.
_Avoid_: embedded text, hidden text (except for text we add under a page image)

**Typeset text layer**:
A text layer drawn as visible text in fonts, as in a born-digital PDF.
_Avoid_: native text, real text

**Prior OCR layer**:
A text layer added by earlier OCR: invisible text laid over a scanned page image.
_Avoid_: hidden text, OCR overlay

**Page sequence gap**:
A break in a book's printed page numbers (a page missing or repeated), suggesting a page was skipped or scanned twice.
_Avoid_: missing page (it may be a duplicate), numbering error

### Recognition

**OCR engine**:
The program that reads text from a page image. Tesseract is the first; others may follow behind the same interface.
_Avoid_: recogniser, OCR backend

**OCR attempt**:
One run of the OCR engine on one page with one set of image cleanup and recognition settings.
_Avoid_: pass, try

**Retry ladder**:
The fixed sequence of OCR attempts tried on a page until one is good enough, after which the page falls back to a page image.
_Avoid_: auto-tuning, retry loop

**OCR confidence**:
How sure the OCR engine is of the text it read, on a 0 to 1 scale. Only comparable within one engine.
_Avoid_: accuracy, score

**Coverage**:
The share of a page's ink that falls inside words the OCR engine recognised. Catches dropped text that OCR confidence misses.
_Avoid_: recall, completeness

**Text-layer quality check**:
The test that decides, page by page, whether an existing text layer is trusted or the page is OCR'd again.
_Avoid_: text validation, OCR detection

### Protection

**Password-protected PDF**:
A PDF encrypted with the standard PDF password scheme, which opens with a password its owner gave the user.
_Avoid_: DRM-protected, locked

**Permission restrictions**:
Flags in a PDF that say what a reader may do with it (copy, print, extract). pdf2epub honours them.
_Avoid_: owner restrictions, soft DRM

**DRM-protected**:
A PDF or wrapper whose access is controlled by vendor rights-management software rather than a user password. pdf2epub refuses it.
_Avoid_: unlocking, cracking, and any wording that suggests pdf2epub takes DRM off a file

**User password**:
The password that opens a password-protected PDF for reading, subject to its permission restrictions.
_Avoid_: open password, document password

**Owner password**:
The password that opens a password-protected PDF with full rights, lifting its permission restrictions.
_Avoid_: permissions password, master password

**Candidate password**:
One password pdf2epub will try against a file, from any source the user gave.
_Avoid_: guess, attempt

**Password source**:
Where a candidate password came from (a password map entry, the environment, a password file line, the command line, or a prompt). Reports name the source, never the password.
_Avoid_: origin, provider
