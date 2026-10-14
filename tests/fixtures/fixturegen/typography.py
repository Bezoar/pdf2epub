"""The ligature and soft-hyphen sample (RFL-AC7, RFL-AC11): ``born-digital/typography.pdf``.

One English paragraph on one page, set line by line in Bitstream Vera (ReportLab's bundled
TrueType font, so the text layer carries the exact code points drawn):

- the ``ﬁ`` and ``ﬂ`` ligature code points (U+FB01, U+FB02);
- a decomposed accented letter: ``e`` followed by U+0301 COMBINING ACUTE ACCENT (in the
  text layer; Vera has no glyph for the accent, so it is drawn as an empty .notdef);
- a soft hyphen (U+00AD) inside a word in mid-line (``some`` U+00AD ``thing``);
- three line ends that break a word: ``exam-`` / ``ple`` (a hyphen, and the joined word
  is an English word), ``well-`` / ``known`` (a real hyphen) and ``informa`` + soft hyphen
  / ``tion``.

The ground truth, ``born-digital/typography.txt``, is the paragraph as an English reader
sees it: ligatures expanded, NFC, no soft hyphens, ``example``, ``well-known`` and
``information``.
"""

import os
from pathlib import Path

import reportlab
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas

PATH = "born-digital/typography.pdf"
GROUND_TRUTH = "born-digital/typography.txt"

TITLE = "Typography Sample"
LANGUAGE = "en"
FONT, SIZE, LEADING = "Vera", 11.0, 14.5
PAGE_WIDTH, PAGE_HEIGHT = 432.0, 648.0
MARGIN_X, TOP, INDENT = 54.0, 560.0, 18.0

SHY = "\u00ad"
LINES = [
    "The \ufb01rst \ufb02oor of the old cafe\u0301 held a quiet",
    f"reading room where some{SHY}thing unusual happened every",
    "evening. One exam-",
    "ple of this was a well-",
    f"known story about the harbour, and the informa{SHY}",
    "tion it gave was useful to everyone.",
]
TEXT = (
    "The first floor of the old café held a quiet reading room where something unusual "
    "happened every evening. One example of this was a well-known story about the harbour, "
    "and the information it gave was useful to everyone."
)

# Vera has no U+0301 glyph, so ReportLab draws it with code 0 (.notdef) and maps that code
# to U+0000 in the font's ToUnicode CMap. Mapping code 0 to U+0301 instead (same length,
# so no offsets move) makes the text layer carry the decomposed letter. Only U+0301 is
# missing from Vera, so code 0 means nothing else here.
NOTDEF_ENTRY, ACCENT_ENTRY = b"<00> <0000>", b"<00> <0301>"


def _map_combining_accent(pdf_path: Path) -> None:
    data = pdf_path.read_bytes()
    assert data.count(NOTDEF_ENTRY) == 1, "expected one ToUnicode entry for code 0"
    pdf_path.write_bytes(data.replace(NOTDEF_ENTRY, ACCENT_ENTRY))


def build(out_dir: Path) -> None:
    font_dir = Path(reportlab.__file__).parent / "fonts"
    pdfmetrics.registerFont(TTFont(FONT, os.fspath(font_dir / "Vera.ttf")))

    pdf_path = out_dir / PATH
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    canvas = Canvas(
        str(pdf_path),
        pagesize=(PAGE_WIDTH, PAGE_HEIGHT),
        invariant=True,
        pageCompression=0,
        lang=LANGUAGE,
    )
    canvas.setTitle(TITLE)
    canvas.setFont(FONT, SIZE)
    y = TOP
    for index, line in enumerate(LINES):
        canvas.drawString(MARGIN_X + (INDENT if index == 0 else 0), y, line)
        y -= LEADING
    canvas.showPage()
    canvas.save()
    _map_combining_accent(pdf_path)

    (out_dir / GROUND_TRUTH).write_text(TEXT + "\n", encoding="utf-8")
