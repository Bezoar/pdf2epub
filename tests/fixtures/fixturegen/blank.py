"""The all-blank born-digital fixtures (RFL-AC24), under ``born-digital/``:

- ``blank-pages.pdf``: three pages with no text and no image (empty content streams);
- ``blank-pages-plus-text.pdf``: the same three pages, then a fourth page holding one
  line of text; its ground truth, ``blank-pages-plus-text.txt``, is that line;
- ``blank-page.pdf``: one blank page inside a document with content (OCR-AC2): a line of
  text on page 1, a blank page 2, a line of text on page 3; its ground truth,
  ``blank-page.txt``, is the two lines, separated by a blank line.
"""

from pathlib import Path

from fixturegen import rawpdf

BLANK = "born-digital/blank-pages.pdf"
PLUS_TEXT = "born-digital/blank-pages-plus-text.pdf"
PLUS_TEXT_TRUTH = "born-digital/blank-pages-plus-text.txt"
BLANK_INSIDE = "born-digital/blank-page.pdf"
BLANK_INSIDE_TRUTH = "born-digital/blank-page.txt"
TEXT = "Only the fourth page has anything on it."
BEFORE, AFTER = "The page after this one is blank.", "The page before this one is blank."

_FONT = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>"


def _pages(contents: list[bytes]) -> bytes:
    """A PDF with one 6 x 9 in page per content stream. Objects: 1 catalog, 2 page tree,
    3 font, then a page and its content stream for each page."""
    kids = b" ".join(b"%d 0 R" % (4 + 2 * i) for i in range(len(contents)))
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [%s] /Count %d >>" % (kids, len(contents)),
        _FONT,
    ]
    for index, content in enumerate(contents):
        objects.append(
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 432 648]"
            b" /Resources << /Font << /F1 3 0 R >> >> /Contents %d 0 R >>" % (5 + 2 * index)
        )
        objects.append(rawpdf.stream(b"", content))
    return rawpdf.document(objects)


def build_blank(out_dir: Path) -> None:
    target = out_dir / BLANK
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(_pages([b""] * 3))


def build_plus_text(out_dir: Path) -> None:
    line = b"BT /F1 12 Tf 54 600 Td (%s) Tj ET" % TEXT.encode("ascii")
    target = out_dir / PLUS_TEXT
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(_pages([b"", b"", b"", line]))
    (out_dir / PLUS_TEXT_TRUTH).write_text(TEXT + "\n", encoding="utf-8")


def _line(text: str) -> bytes:
    return b"BT /F1 12 Tf 54 600 Td (%s) Tj ET" % text.encode("ascii")


def build_blank_inside(out_dir: Path) -> None:
    target = out_dir / BLANK_INSIDE
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(_pages([_line(BEFORE), b"", _line(AFTER)]))
    (out_dir / BLANK_INSIDE_TRUTH).write_text(f"{BEFORE}\n\n{AFTER}\n", encoding="utf-8")
