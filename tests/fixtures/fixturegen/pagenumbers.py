"""The page-label and printed-page-number fixtures (RFL-AC17, RFL-AC20, RFL-AC21,
EPUB-AC13).

Each page holds one short English paragraph in 11 pt Times-Roman (or, on a chapter
opener, a 24 pt title first) and, unless it is unnumbered, its printed page number (its
*folio*) centred in the footer. A plate is a page holding only a framed picture and its
caption.

Born-digital, with visible text and PDF page labels:

- ``born-digital/page-labels.pdf``: 24 pages labelled ``i``-``iv`` then ``1``-``20``,
  with matching folios;
- ``born-digital/odd-page-labels.pdf``: 4 pages, no folios, labelled ``i``, ``i``,
  ``A&B 1`` and ``<2>``.

Scanned (the page-numbers scan): every page is a 75 DPI bitonal image of its text (each
word a bar of ink), under
an invisible text layer (render mode 3) like a scan with a good OCR layer, and no page
labels:

- ``scanned/page-numbers-missing.pdf``: 30 pages with folios 1-16 then 18-31, so printed
  page 17 is missing (PDF page 17 shows 18);
- ``scanned/page-numbers-repeated.pdf``: 30 pages with folios 1-9, 9, 10-29, so printed
  page 9 appears twice (PDF pages 9 and 10);
- ``scanned/page-numbers-front-matter.pdf``: roman front matter ``i``-``x``, then
  ``1``-``40``, with an unnumbered chapter opener where 13 would be and an unnumbered
  plate between 30 and 31 (51 pages).

Born-digital, with visible text and no page labels:

- ``born-digital/page-numbers-tripled.pdf``: 21 pages with folios 1-9, 9, 9, 10-19, so
  printed page 9 appears three times in a row (PDF pages 9 to 11).

Each ground truth (the ``.txt`` beside the PDF) is the book's text without folios: titles,
paragraphs and plate captions, one per line, separated by blank lines.

The files are written by ``rawpdf``: content streams uncompressed, page images
run-length encoded by the pure-Python encoder below, and the images drawn without fonts,
so the bytes don't depend on zlib, FreeType or Pillow's fonts.
"""

import random
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw
from reportlab.pdfbase.pdfmetrics import stringWidth

from fixturegen import prose, rawpdf

PAGE_LABELS = "born-digital/page-labels.pdf"
PAGE_LABELS_TRUTH = "born-digital/page-labels.txt"
ODD_LABELS = "born-digital/odd-page-labels.pdf"
ODD_LABELS_TRUTH = "born-digital/odd-page-labels.txt"
MISSING = "scanned/page-numbers-missing.pdf"
MISSING_TRUTH = "scanned/page-numbers-missing.txt"
REPEATED = "scanned/page-numbers-repeated.pdf"
REPEATED_TRUTH = "scanned/page-numbers-repeated.txt"
TRIPLED = "born-digital/page-numbers-tripled.pdf"
TRIPLED_TRUTH = "born-digital/page-numbers-tripled.txt"
FRONT_MATTER = "scanned/page-numbers-front-matter.pdf"
FRONT_MATTER_TRUTH = "scanned/page-numbers-front-matter.txt"

LANGUAGE = "en"
PAGE_WIDTH, PAGE_HEIGHT = 432.0, 648.0  # 6 x 9 in
MARGIN_X, BODY_TOP = 54.0, 576.0
TEXT_WIDTH = PAGE_WIDTH - 2 * MARGIN_X
BODY_FONT, BODY_SIZE, LEADING, INDENT = "Times-Roman", 11.0, 14.5, 18.0
TITLE_FONT, TITLE_SIZE = "Times-Bold", 24.0
FOLIO_SIZE, FOLIO_Y = 9.0, 40.0
_FONTS = {"F1": BODY_FONT, "F2": TITLE_FONT}
DPI = 75
SCALE = DPI / 72


@dataclass(frozen=True)
class Page:
    folio: str | None
    """The printed page number in the footer, or None for an unnumbered page."""
    title: str | None = None
    """A chapter opener's title."""
    plate: str | None = None
    """A plate's caption; a plate has no body text."""


@dataclass(frozen=True)
class _Run:
    """One line of text to draw: font resource, size, position (PDF points)."""

    font: str
    size: float
    x: float
    y: float
    text: str


# --- Page content -----------------------------------------------------------------------


def _break_lines(text: str) -> list[str]:
    lines: list[str] = []
    current: list[str] = []
    for word in text.split():
        width = TEXT_WIDTH - (INDENT if not lines else 0)
        if current and stringWidth(" ".join([*current, word]), BODY_FONT, BODY_SIZE) > width:
            lines.append(" ".join(current))
            current = []
        current.append(word)
    lines.append(" ".join(current))
    return lines


def _lay_out(page: Page, rng: random.Random) -> tuple[list[_Run], list[str]]:
    """The text runs of ``page`` and its ground-truth entries."""
    runs: list[_Run] = []
    truth: list[str] = []
    y = BODY_TOP - BODY_SIZE
    if page.plate is not None:
        width = stringWidth(page.plate, BODY_FONT, BODY_SIZE)
        runs.append(_Run("F1", BODY_SIZE, (PAGE_WIDTH - width) / 2, 180.0, page.plate))
        truth.append(page.plate)
    else:
        if page.title is not None:
            runs.append(_Run("F2", TITLE_SIZE, MARGIN_X, BODY_TOP - TITLE_SIZE, page.title))
            truth.append(page.title)
            y -= 4 * LEADING
        paragraph = prose.paragraph(rng, 3, 4)
        truth.append(paragraph)
        for index, line in enumerate(_break_lines(paragraph)):
            runs.append(_Run("F1", BODY_SIZE, MARGIN_X + (0 if index else INDENT), y, line))
            y -= LEADING
    if page.folio is not None:
        width = stringWidth(page.folio, BODY_FONT, FOLIO_SIZE)
        runs.append(_Run("F1", FOLIO_SIZE, (PAGE_WIDTH - width) / 2, FOLIO_Y, page.folio))
    return runs, truth


def _escape(text: str) -> bytes:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)").encode("cp1252")


def _text_stream(runs: list[_Run], invisible: bool) -> bytes:
    out = [b"BT", b"3 Tr" if invisible else b"0 Tr"]
    for run in runs:
        out.append(
            b"/%s %g Tf 1 0 0 1 %g %g Tm (%s) Tj"
            % (run.font.encode(), run.size, run.x, run.y, _escape(run.text))
        )
    out.append(b"ET")
    return b"\n".join(out)


# --- Page images ------------------------------------------------------------------------


def _scan(runs: list[_Run], plate: bool) -> Image.Image:
    """A bitonal page image of ``runs``: each word is a solid bar of ink at the place and
    width the text layer gives it, as in a low-resolution scan. No font is drawn, so the
    image doesn't change with Pillow's fonts or FreeType."""
    size = (round(PAGE_WIDTH * SCALE), round(PAGE_HEIGHT * SCALE))
    image = Image.new("1", size, 1)
    draw = ImageDraw.Draw(image)
    if plate:
        draw.rectangle(
            [MARGIN_X * SCALE, 120 * SCALE, (PAGE_WIDTH - MARGIN_X) * SCALE, 420 * SCALE],
            outline=0,
            width=2,
        )
    for run in runs:
        font = _FONTS[run.font]
        space = stringWidth(" ", font, run.size)
        bottom = round((PAGE_HEIGHT - run.y) * SCALE)
        top = bottom - max(1, round(run.size * 0.5 * SCALE))
        x = run.x
        for word in run.text.split():
            width = stringWidth(word, font, run.size)
            draw.rectangle([round(x * SCALE), top, round((x + width) * SCALE) - 1, bottom], fill=0)
            x += width + space
    return image


def run_length(data: bytes) -> bytes:
    """``data`` encoded for ``/RunLengthDecode`` (PDF 32000-1, 7.4.5)."""
    out = bytearray()
    literal = bytearray()
    i = 0
    while i < len(data):
        run = 1
        while i + run < len(data) and run < 128 and data[i + run] == data[i]:
            run += 1
        if run >= 2:
            if literal:
                out += bytes([len(literal) - 1]) + literal
                literal.clear()
            out += bytes([257 - run, data[i]])
            i += run
            continue
        literal.append(data[i])
        if len(literal) == 128:
            out += bytes([127]) + literal
            literal.clear()
        i += 1
    if literal:
        out += bytes([len(literal) - 1]) + literal
    return bytes(out + b"\x80")


# --- The PDF ----------------------------------------------------------------------------


def _pdf(pages: list[Page], scanned: bool, labels: bytes | None, title: str) -> tuple[bytes, str]:
    """The PDF of ``pages`` and its ground truth. ``labels`` is the ``/Nums`` array's
    content of a ``/PageLabels`` number tree, or None for no page labels."""
    rng = random.Random(f"{title}/{len(pages)}")
    per_page = 3 if scanned else 2
    kids = b" ".join(b"%d 0 R" % (6 + per_page * i) for i in range(len(pages)))
    page_labels = b" /PageLabels << /Nums [%s] >>" % labels if labels is not None else b""
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R /Lang (%s)%s >>" % (LANGUAGE.encode(), page_labels),
        b"<< /Type /Pages /Kids [%s] /Count %d >>" % (kids, len(pages)),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /%s /Encoding /WinAnsiEncoding >>"
        % BODY_FONT.encode(),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /%s /Encoding /WinAnsiEncoding >>"
        % TITLE_FONT.encode(),
        b"<< /Title (%s) >>" % _escape(title),
    ]
    truth: list[str] = []
    for index, page in enumerate(pages):
        runs, page_truth = _lay_out(page, rng)
        truth.extend(page_truth)
        number = 6 + per_page * index
        content = _text_stream(runs, invisible=scanned)
        xobjects = b""
        if scanned:
            image = _scan(runs, plate=page.plate is not None)
            xobjects = b" /XObject << /Im0 %d 0 R >>" % (number + 2)
            content = b"q %g 0 0 %g 0 0 cm /Im0 Do Q\n" % (PAGE_WIDTH, PAGE_HEIGHT) + content
        objects.append(
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %g %g]"
            b" /Resources << /Font << /F1 3 0 R /F2 4 0 R >>%s >> /Contents %d 0 R >>"
            % (PAGE_WIDTH, PAGE_HEIGHT, xobjects, number + 1)
        )
        objects.append(rawpdf.stream(b"", content))
        if scanned:
            objects.append(
                rawpdf.stream(
                    b"/Type /XObject /Subtype /Image /Width %d /Height %d"
                    b" /ColorSpace /DeviceGray /BitsPerComponent 1 /Filter /RunLengthDecode"
                    % image.size,
                    run_length(image.tobytes()),
                )
            )
    return rawpdf.document(objects, info=5), "\n\n".join(truth) + "\n"


def _write(out_dir: Path, path: str, truth_path: str, pdf: tuple[bytes, str]) -> None:
    target = out_dir / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(pdf[0])
    (out_dir / truth_path).write_text(pdf[1], encoding="utf-8")


def _roman(number: int) -> str:
    return ["i", "ii", "iii", "iv", "v", "vi", "vii", "viii", "ix", "x"][number - 1]


def build_page_labels(out_dir: Path) -> None:
    pages = [Page(_roman(n)) for n in range(1, 5)] + [Page(str(n)) for n in range(1, 21)]
    pages[4] = Page("1", title="Chapter One")
    labels = b"0 << /S /r >> 4 << /S /D >>"
    _write(out_dir, PAGE_LABELS, PAGE_LABELS_TRUTH, _pdf(pages, False, labels, "Page Labels"))


def build_odd_labels(out_dir: Path) -> None:
    pages = [Page(None) for _ in range(4)]
    labels = b"0 << /S /r >> 1 << /S /r >> 2 << /S /D /P (A&B ) >> 3 << /P (<2>) >>"
    _write(out_dir, ODD_LABELS, ODD_LABELS_TRUTH, _pdf(pages, False, labels, "Odd Labels"))


def build_missing(out_dir: Path) -> None:
    folios = [*range(1, 17), *range(18, 32)]
    pages = [Page(str(n)) for n in folios]
    _write(out_dir, MISSING, MISSING_TRUTH, _pdf(pages, True, None, "Missing Page"))


def build_repeated(out_dir: Path) -> None:
    folios = [*range(1, 10), *range(9, 30)]
    pages = [Page(str(n)) for n in folios]
    _write(out_dir, REPEATED, REPEATED_TRUTH, _pdf(pages, True, None, "Repeated Page"))


def build_front_matter(out_dir: Path) -> None:
    pages = [Page(_roman(n)) for n in range(1, 11)]
    for n in range(1, 41):
        if n == 13:
            pages.append(Page(None, title="Chapter Two"))
            continue
        pages.append(Page(str(n)))
        if n == 30:
            pages.append(Page(None, plate="Plate 1. The harbour at dawn."))
    _write(out_dir, FRONT_MATTER, FRONT_MATTER_TRUTH, _pdf(pages, True, None, "Front Matter"))


def build_tripled(out_dir: Path) -> None:
    folios = [*range(1, 10), 9, *range(9, 20)]
    pages = [Page(str(n)) for n in folios]
    _write(out_dir, TRIPLED, TRIPLED_TRUTH, _pdf(pages, False, None, "Tripled Page"))
