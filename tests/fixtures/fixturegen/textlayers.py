"""The text-layer quality check's synthetic fixtures (TST-R3 "Must reject" and "a scan with
a good invisible OCR layer"; OCR-AC3 to OCR-AC6, OCR-AC9).

All four are the same 4-page book: on each page a running header (9 pt Times-Italic), as
many lines of English prose (11 pt Times-Roman) as fill the page, and a centred page
number. The prose comes from ``prose`` with a fixed seed, so every word is a dictionary
word.

- ``scanned/ocr-layer.pdf`` (must trust): each page a 300 DPI bitonal scan of the book's
  page, under an invisible text layer (render mode 3) with every line of the page at the
  place it was drawn, as a good OCR program writes it;
- ``must-reject/garbled-layer.pdf``: the same scans, under an invisible layer with every
  line in its place but each letter of each word replaced by a random letter of the same
  case (valid characters, nonsense words);
- ``must-reject/half-layer.pdf``: the same scans, under an invisible layer holding only
  the lines in the top half of each page (header included);
- ``must-reject/no-tounicode.pdf``: the book typeset (visible text, no scan) in a Type 3
  bitmap font, as old TeX (dvips) PDFs carry, whose glyphs are named ``/g<code>`` and
  which has no ``/ToUnicode`` map, so no extractor can tell which character a glyph is.
  The glyph bitmaps are PDFium's own rendering of Times-Roman at 100 px per em, cut to
  bitonal.

Each ground truth (the ``.txt`` beside the PDF) is the book's text without header and page
numbers, as a reader sees it: its paragraphs, separated by blank lines.

How the bytes stay the same on every platform: as in ``scans``, every bitmap is rendered
by the pinned PDFium with its built-in fonts only, cut to bitonal at mid-grey; the scans
are CCITT Group 4 encoded and the glyph bitmaps run-length encoded by ``pagenumbers``'
pure-Python encoder; the PDFs are written by ``rawpdf``, uncompressed.
"""

import math
import random
from dataclasses import dataclass, replace
from pathlib import Path

from PIL import Image
from reportlab.pdfbase.pdfmetrics import stringWidth

from fixturegen import pagenumbers, prose, rawpdf, scans

OCR_LAYER = "scanned/ocr-layer.pdf"
OCR_LAYER_TRUTH = "scanned/ocr-layer.txt"
GARBLED_LAYER = "must-reject/garbled-layer.pdf"
GARBLED_LAYER_TRUTH = "must-reject/garbled-layer.txt"
HALF_LAYER = "must-reject/half-layer.pdf"
HALF_LAYER_TRUTH = "must-reject/half-layer.txt"
NO_TOUNICODE = "must-reject/no-tounicode.pdf"
NO_TOUNICODE_TRUTH = "must-reject/no-tounicode.txt"

TITLE = "The Harbour Ledger"
LANGUAGE = "en"
PAGES = 4
PAGE_WIDTH, PAGE_HEIGHT = 432.0, 648.0  # 6 x 9 in
BODY_FONT, HEADER_FONT = "Times-Roman", "Times-Italic"
BODY_SIZE, SMALL_SIZE, LEADING = 11.0, 9.0, 14.5
MARGIN_X, HEADER_Y, BODY_TOP, BODY_BOTTOM, FOLIO_Y, INDENT = 54.0, 600.0, 560.0, 72.0, 40.0, 18.0
TEXT_WIDTH = PAGE_WIDTH - 2 * MARGIN_X
_SEED = 4422
_GARBLE_SEED = 4423
_FONTS = {BODY_FONT: b"F1", HEADER_FONT: b"F2"}
# The Type 3 font's glyphs: bitmaps at this many pixels per em, in a cell from
# _CELL_LEFT to the advance plus _CELL_RIGHT, and from _CELL_BOTTOM to _CELL_TOP (glyph
# units, 1000 per em).
_GLYPH_PX = 100
_CELL_LEFT, _CELL_RIGHT, _CELL_BOTTOM, _CELL_TOP = -50, 50, -250, 950


@dataclass(frozen=True)
class _Run:
    """One line of text to draw: font, size and baseline start (PDF points)."""

    font: str
    size: float
    x: float
    y: float
    text: str


# --- The book ---------------------------------------------------------------------------


def _break_lines(text: str) -> list[str]:
    lines: list[str] = []
    current: list[str] = []
    for word in text.split():
        width = TEXT_WIDTH - (0 if lines else INDENT)
        if current and stringWidth(" ".join([*current, word]), BODY_FONT, BODY_SIZE) > width:
            lines.append(" ".join(current))
            current = []
        current.append(word)
    lines.append(" ".join(current))
    return lines


def _book() -> tuple[list[list[_Run]], str]:
    """The runs of each page and the book's ground truth. Paragraphs run on from page to
    page; the last one ends where the last page is full."""
    rng = random.Random(_SEED)
    pages: list[list[_Run]] = []
    paragraphs: list[list[str]] = []
    pending: list[tuple[str, bool]] = []  # lines still to place, and whether each starts one
    for number in range(1, PAGES + 1):
        header = stringWidth(TITLE, HEADER_FONT, SMALL_SIZE)
        folio = stringWidth(str(number), BODY_FONT, SMALL_SIZE)
        runs = [_Run(HEADER_FONT, SMALL_SIZE, (PAGE_WIDTH - header) / 2, HEADER_Y, TITLE)]
        y = BODY_TOP
        while y >= BODY_BOTTOM:
            if not pending:
                lines = _break_lines(prose.paragraph(rng, 4, 6))
                pending = [(line, index == 0) for index, line in enumerate(lines)]
                paragraphs.append([])
            line, first = pending.pop(0)
            runs.append(_Run(BODY_FONT, BODY_SIZE, MARGIN_X + (INDENT if first else 0), y, line))
            paragraphs[-1].append(line)
            y -= LEADING
        runs.append(_Run(BODY_FONT, SMALL_SIZE, (PAGE_WIDTH - folio) / 2, FOLIO_Y, str(number)))
        pages.append(runs)
    truth = "\n\n".join(" ".join(lines) for lines in paragraphs) + "\n"
    return pages, truth


def _escape(text: bytes) -> bytes:
    return text.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")


def _text_stream(runs: list[_Run], invisible: bool) -> bytes:
    """The runs in the standard Times fonts (``/F1``, ``/F2``), visible or not."""
    out = [b"BT", b"3 Tr" if invisible else b"0 Tr"]
    for run in runs:
        out.append(
            b"/%s %g Tf 1 0 0 1 %g %g Tm (%s) Tj"
            % (_FONTS[run.font], run.size, run.x, run.y, _escape(run.text.encode("cp1252")))
        )
    out.append(b"ET")
    return b"\n".join(out)


def _font_objects(first: int) -> list[bytes]:
    """The two standard Times fonts, as objects ``first`` and ``first + 1``."""
    return [
        b"<< /Type /Font /Subtype /Type1 /BaseFont /%s /Encoding /WinAnsiEncoding >>"
        % font.encode()
        for font in (BODY_FONT, HEADER_FONT)
    ]


def _typeset(pages: list[list[_Run]]) -> bytes:
    """The book with visible text in the standard Times fonts: what the scans are of."""
    objects = _catalog(len(pages), per_page=2)
    objects.extend(_font_objects(4))
    for index, runs in enumerate(pages):
        number = 6 + 2 * index
        objects.append(_page(number + 1, b"/Font << /F1 4 0 R /F2 5 0 R >>"))
        objects.append(rawpdf.stream(b"", _text_stream(runs, invisible=False)))
    return rawpdf.document(objects, info=3)


def _catalog(count: int, per_page: int) -> list[bytes]:
    """Objects 1 to 3: catalog, page tree (pages from object 6, ``per_page`` objects
    each) and Info."""
    kids = b" ".join(b"%d 0 R" % (6 + per_page * i) for i in range(count))
    return [
        b"<< /Type /Catalog /Pages 2 0 R /Lang (%s) >>" % LANGUAGE.encode(),
        b"<< /Type /Pages /Kids [%s] /Count %d >>" % (kids, count),
        b"<< /Title (%s) >>" % TITLE.encode("ascii"),
    ]


def _page(contents: int, resources: bytes) -> bytes:
    return (
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %g %g]"
        b" /Resources << %s >> /Contents %d 0 R >>"
        % (
            PAGE_WIDTH,
            PAGE_HEIGHT,
            resources,
            contents,
        )
    )


# --- The scans with invisible layers ----------------------------------------------------


def _layered(images: list[Image.Image], layers: list[list[_Run]]) -> bytes:
    """One page per scan, the scan filling the page, under an invisible text layer of the
    page's runs."""
    objects = _catalog(len(images), per_page=3)
    objects.extend(_font_objects(4))
    for index, (image, runs) in enumerate(zip(images, layers, strict=True)):
        number = 6 + 3 * index
        resources = b"/Font << /F1 4 0 R /F2 5 0 R >> /XObject << /Im0 %d 0 R >>" % (number + 2)
        objects.append(_page(number + 1, resources))
        scan = b"q %g 0 0 %g 0 0 cm /Im0 Do Q\n" % (PAGE_WIDTH, PAGE_HEIGHT)
        objects.append(rawpdf.stream(b"", scan + _text_stream(runs, invisible=True)))
        objects.append(
            rawpdf.stream(
                b"/Type /XObject /Subtype /Image /Width %d /Height %d /ColorSpace /DeviceGray"
                b" /BitsPerComponent 1 /Filter /CCITTFaxDecode"
                b" /DecodeParms << /K -1 /Columns %d /Rows %d /BlackIs1 false >>"
                % (image.width, image.height, image.width, image.height),
                scans.group4(image),
            )
        )
    return rawpdf.document(objects, info=3)


def _garbled(text: str, rng: random.Random) -> str:
    """``text`` with each letter replaced by a random letter of the same case."""
    lower, upper = "abcdefghijklmnopqrstuvwxyz", "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    return "".join(
        rng.choice(upper) if c.isupper() else rng.choice(lower) if c.isalpha() else c for c in text
    )


def _write(out_dir: Path, path: str, truth_path: str, pdf: bytes, truth: str) -> None:
    target = out_dir / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(pdf)
    (out_dir / truth_path).write_text(truth, encoding="utf-8")


def _scans(pages: list[list[_Run]]) -> list[Image.Image]:
    return scans._render(_typeset(pages))


def build_ocr_layer(out_dir: Path) -> None:
    pages, truth = _book()
    _write(out_dir, OCR_LAYER, OCR_LAYER_TRUTH, _layered(_scans(pages), pages), truth)


def build_garbled_layer(out_dir: Path) -> None:
    pages, truth = _book()
    rng = random.Random(_GARBLE_SEED)
    layers = [[replace(run, text=_garbled(run.text, rng)) for run in runs] for runs in pages]
    _write(out_dir, GARBLED_LAYER, GARBLED_LAYER_TRUTH, _layered(_scans(pages), layers), truth)


def build_half_layer(out_dir: Path) -> None:
    pages, truth = _book()
    layers = [[run for run in runs if run.y >= PAGE_HEIGHT / 2] for runs in pages]
    _write(out_dir, HALF_LAYER, HALF_LAYER_TRUTH, _layered(_scans(pages), layers), truth)


# --- The Type 3 font with no ToUnicode map ----------------------------------------------


def _glyphs(characters: list[str]) -> list[Image.Image]:
    """Each character's bitmap: Times-Roman at ``_GLYPH_PX`` pixels per em, in its cell."""
    unit = _GLYPH_PX / 1000  # pixels per glyph unit
    objects = _catalog(len(characters), per_page=2)
    objects.extend(_font_objects(4))
    for index, character in enumerate(characters):
        advance = stringWidth(character, BODY_FONT, 1000)
        width = math.ceil((advance + _CELL_RIGHT - _CELL_LEFT) * unit)
        height = round((_CELL_TOP - _CELL_BOTTOM) * unit)
        number = 6 + 2 * index
        objects.append(
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %d %d]"
            b" /Resources << /Font << /F1 4 0 R >> >> /Contents %d 0 R >>"
            % (width, height, number + 1)
        )
        text = b"BT /F1 %d Tf 1 0 0 1 %g %g Tm (%s) Tj ET" % (
            _GLYPH_PX,
            -_CELL_LEFT * unit,
            -_CELL_BOTTOM * unit,
            _escape(character.encode("cp1252")),
        )
        objects.append(rawpdf.stream(b"", text))
    return scans._render(rawpdf.document(objects, info=3), dpi=72)


def _no_tounicode(pages: list[list[_Run]]) -> bytes:
    """The book typeset in one Type 3 bitmap font with no ``/ToUnicode``: code 32 is the
    space (named ``/space``), every other character gets a code from 33 up, named
    ``/g<code>``. Objects: 1-3 catalog, pages, Info; 4 the font; 5 its glyph procedures'
    resources; then each glyph's procedure and bitmap, then each page and its content."""
    characters = sorted({c for runs in pages for run in runs for c in run.text} - {" "})
    codes = {c: 33 + index for index, c in enumerate(characters)}
    codes[" "] = 32
    bitmaps = _glyphs(characters)
    first_glyph = 6
    first_page = first_glyph + 2 * len(characters)
    kids = b" ".join(b"%d 0 R" % (first_page + 2 * i) for i in range(len(pages)))
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R /Lang (%s) >>" % LANGUAGE.encode(),
        b"<< /Type /Pages /Kids [%s] /Count %d >>" % (kids, len(pages)),
        b"<< /Title (%s) >>" % TITLE.encode("ascii"),
    ]
    last = 32 + len(characters)
    names = b" ".join(b"/g%d" % codes[c] for c in characters)
    widths = b" ".join(b"%d" % round(stringWidth(c, BODY_FONT, 1000)) for c in [" ", *characters])
    procs = b" ".join(
        b"/g%d %d 0 R" % (codes[c], first_glyph + 2 * i) for i, c in enumerate(characters)
    )
    space_proc = first_page + 2 * len(pages)
    objects.append(
        b"<< /Type /Font /Subtype /Type3 /FontBBox [%d %d %d %d]"
        b" /FontMatrix [0.001 0 0 0.001 0 0] /CharProcs << /space %d 0 R %s >>"
        b" /Encoding << /Type /Encoding /Differences [32 /space %s] >>"
        b" /FirstChar 32 /LastChar %d /Widths [%s] /Resources 5 0 R >>"
        % (_CELL_LEFT, _CELL_BOTTOM, 1100, _CELL_TOP, space_proc, procs, names, last, widths)
    )
    xobjects = b" ".join(
        b"/B%d %d 0 R" % (codes[c], first_glyph + 2 * i + 1) for i, c in enumerate(characters)
    )
    objects.append(b"<< /XObject << %s >> >>" % xobjects)
    unit = 1000 / _GLYPH_PX  # glyph units per pixel
    for character, bitmap in zip(characters, bitmaps, strict=True):
        advance = round(stringWidth(character, BODY_FONT, 1000))
        proc = b"%d 0 %d %d %d %d d1 q %g 0 0 %g %d %d cm /B%d Do Q" % (
            advance,
            _CELL_LEFT,
            _CELL_BOTTOM,
            advance + _CELL_RIGHT,
            _CELL_TOP,
            bitmap.width * unit,
            bitmap.height * unit,
            _CELL_LEFT,
            _CELL_BOTTOM,
            codes[character],
        )
        objects.append(rawpdf.stream(b"", proc))
        objects.append(
            rawpdf.stream(
                b"/Type /XObject /Subtype /Image /Width %d /Height %d /ImageMask true"
                b" /BitsPerComponent 1 /Filter /RunLengthDecode" % bitmap.size,
                pagenumbers.run_length(bitmap.tobytes()),
            )
        )
    for index, runs in enumerate(pages):
        number = first_page + 2 * index
        objects.append(
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %g %g]"
            b" /Resources << /Font << /T3 4 0 R >> >> /Contents %d 0 R >>"
            % (PAGE_WIDTH, PAGE_HEIGHT, number + 1)
        )
        out = [b"BT"]
        for run in runs:
            encoded = bytes(codes[c] for c in run.text)
            out.append(
                b"/T3 %g Tf 1 0 0 1 %g %g Tm (%s) Tj" % (run.size, run.x, run.y, _escape(encoded))
            )
        out.append(b"ET")
        objects.append(rawpdf.stream(b"", b"\n".join(out)))
    objects.append(rawpdf.stream(b"", b"%d 0 d0" % round(stringWidth(" ", BODY_FONT, 1000))))
    return rawpdf.document(objects, info=3)


def build_no_tounicode(out_dir: Path) -> None:
    pages, truth = _book()
    _write(out_dir, NO_TOUNICODE, NO_TOUNICODE_TRUTH, _no_tounicode(pages), truth)
