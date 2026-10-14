# pdf2epub

pdf2epub converts PDF books, born-digital or scanned, into reflowable EPUB 3 books for personal reading and backup. It converts one file at a time or a whole batch, runs fully offline, and writes EPUBs that pass [epubcheck](https://www.w3.org/publishing/epubcheck/).

Opens password-protected PDFs only with a password you supply. Honours permission restrictions. Does not remove DRM.

> **Status:** early development. The command converts born-digital PDFs end to end; structure recovery, OCR, passwords and the full set of options are being built (see the [v1 plan](docs/plans/v1.md)).

## Install

pdf2epub needs Python 3.12 or later. Install it from this repository with [uv](https://docs.astral.sh/uv/):

```sh
uv tool install git+https://github.com/Bezoar/pdf2epub
```

or with pipx:

```sh
pipx install git+https://github.com/Bezoar/pdf2epub
```

## Usage

```sh
pdf2epub book.pdf            # writes book.epub next to book.pdf
pdf2epub a.pdf b.pdf         # a batch: one failing file never stops the others
pdf2epub --help              # every option
```

A single conversion prints one result line to stderr, for example:

```text
✓ /home/me/books/book.pdf → /home/me/books/book.epub (212 pages, 8.4s)
```

The exit code is `0` when every conversion succeeded or was skipped, and `1` when any failed.

## Legal scope

pdf2epub is meant to be clearly on the right side of anti-circumvention law (such as US DMCA §1201 and Art. 6 of the EU InfoSoc Directive). Its scope is fixed as follows. This is risk reduction, not legal advice.

- **No circumvention.** pdf2epub never circumvents DRM or any other access or copy control, and nothing in its code, documentation or plans attempts to.
- **Passwords you supply.** The only decryption it performs is opening a password-protected PDF, one that uses the PDF Standard security handler, with a password you supply: a password its owner gave you.
- **DRM is refused.** DRM-protected files are refused: any PDF with a security handler other than the Standard one, and vendor wrappers such as Readium LCP or Adobe `.acsm` tokens. No password is tried against them.
- **Permission restrictions.** pdf2epub honours permission restrictions. If a PDF forbids copying or extracting its content, the conversion fails as `restricted`, and only the owner password lifts that. There is no option to override it.
- **No password guessing.** It tries at most 25 candidate passwords per file, and every one comes from a source you named. Supplying more is a usage error.
- **Your EPUB, your responsibility.** The EPUB is written unencrypted, whatever protection the PDF had: protecting it is your responsibility.

## Installing Tesseract

Scanned PDFs need the [Tesseract](https://github.com/tesseract-ocr/tesseract) OCR engine and its language data:

```sh
brew install tesseract tesseract-lang                 # macOS (Homebrew)
sudo apt install tesseract-ocr tesseract-ocr-eng      # Debian and Ubuntu
sudo apt install tesseract-ocr-fra tesseract-ocr-deu  # more languages: tesseract-ocr-<code>
```

## Development

See [AGENTS.md](AGENTS.md) for the specification, the plan and how to work on the code.

## Licence

[MIT](LICENSE).
