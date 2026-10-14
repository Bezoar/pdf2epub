"""Pages that can't be reflowed faithfully (RFL-R11, RFL-R13): the two-column set, the
table page and the math page, in four born-digital fixtures.

Every page is US Letter, with a centred running header (9 pt Times-Italic) and a centred
page number in the footer (9 pt), both of them furniture. Pages are of four kinds:

- **prose**: indented paragraphs of 10 pt Times-Roman across the full text width;
- **two-column**: two columns of prose, 243 pt wide with an 18 pt gutter, each holding
  two whole paragraphs; the centred header and page number cross the gutter;
- **table**: a short paragraph, then a ruled grid of 4 columns and 5 rows of cell text,
  then a displayed equation in Times-Italic;
- **math**: a short paragraph, then ten displayed equations in Times-Italic, made of
  single-letter variables and the operators ``=``, ``+``, ``<`` and the multiplication,
  division and plus-minus signs.

The fixtures (pages by kind):

- ``born-digital/two-column.pdf``: 1 prose, 2-4 two-column (RFL-AC8, EPUB-AC7, MAIN-AC-B);
- ``born-digital/complex-page.pdf``: 1 and 3 prose, 2 table with its equation (RFL-AC9);
- ``born-digital/fallbacks.pdf``: 3 table, 5 two-column, 7 math, the other 5 of its 8
  pages prose (API-AC8);
- ``born-digital/complex-pages.pdf``: 3 and 8 table, 7 and 9 math, the other 6 of its 10
  pages prose (CLI-AC14).

Each ground truth (``.txt`` beside the PDF) holds the pages in order, without furniture.
Each page starts with a line ``[page N: KIND]``; then, separated by blank lines, its
paragraphs on one line each; a two-column page has ``[left]`` and ``[right]`` lines before
each column's paragraphs; a table page gives its rows as cell texts separated by `` | ``
after a ``[table]`` line, then its equation after ``[equation]``; a math page gives its
equations after ``[equations]``, one per line.
"""

import random
from pathlib import Path

from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen.canvas import Canvas

from fixturegen import prose

TWO_COLUMN = "born-digital/two-column.pdf"
TWO_COLUMN_TRUTH = "born-digital/two-column.txt"
COMPLEX_PAGE = "born-digital/complex-page.pdf"
COMPLEX_PAGE_TRUTH = "born-digital/complex-page.txt"
FALLBACKS = "born-digital/fallbacks.pdf"
FALLBACKS_TRUTH = "born-digital/fallbacks.txt"
COMPLEX_PAGES = "born-digital/complex-pages.pdf"
COMPLEX_PAGES_TRUTH = "born-digital/complex-pages.txt"

LANGUAGE = "en"
PAGE_WIDTH, PAGE_HEIGHT = 612.0, 792.0
MARGIN_X, TOP, BOTTOM = 54.0, 720.0, 72.0
TEXT_WIDTH = PAGE_WIDTH - 2 * MARGIN_X
GUTTER = 18.0
COLUMN_WIDTH = (TEXT_WIDTH - GUTTER) / 2
BODY_FONT, BODY_SIZE, LEADING, INDENT = "Times-Roman", 10.0, 12.5, 15.0
MATH_FONT = "Times-Italic"
HEADER_FONT, SMALL_SIZE, HEADER_Y, FOLIO_Y = "Times-Italic", 9.0, 750.0, 40.0
CELL_HEIGHT = 20.0

TABLE = [
    ["Vessel", "Departs", "Arrives", "Passengers"],
    ["Morning Star", "06:15", "08:40", "112"],
    ["Grey Heron", "09:30", "11:55", "87"],
    ["Lantern", "13:05", "15:20", "140"],
    ["Northern Light", "17:45", "20:10", "64"],
]
TABLE_COLUMNS = [MARGIN_X, MARGIN_X + 130, MARGIN_X + 220, MARGIN_X + 310, MARGIN_X + 410]
TIMES, DIVIDED, PLUS_MINUS = "×", "÷", "±"  # noqa: RUF001
EQUATIONS = [
    f"h = a {TIMES} s + b",
    f"d = v {TIMES} t {PLUS_MINUS} e",
    "k < m + n",
    f"x {DIVIDED} y = z {TIMES} w",
    f"p + q = r {TIMES} c",
    f"f = g {DIVIDED} (u + 1)",
    f"a {TIMES} b < c + d",
    f"t = (d {DIVIDED} v) {PLUS_MINUS} 2",
    f"n + 1 = m {TIMES} k",
    f"s = r {TIMES} r + c",
]


def _wrap(text: str, width: float) -> list[str]:
    """Greedy line breaking at spaces, with the first line indented."""
    lines: list[str] = []
    current: list[str] = []
    for word in text.split():
        room = width - (INDENT if not lines else 0)
        if current and stringWidth(" ".join([*current, word]), BODY_FONT, BODY_SIZE) > room:
            lines.append(" ".join(current))
            current = []
        current.append(word)
    lines.append(" ".join(current))
    return lines


def _paragraphs(canvas: Canvas, texts: list[str], x: float, width: float, y: float) -> float:
    canvas.setFont(BODY_FONT, BODY_SIZE)
    for text in texts:
        for index, line in enumerate(_wrap(text, width)):
            canvas.drawString(x + (INDENT if index == 0 else 0), y, line)
            y -= LEADING
    assert y > BOTTOM, "page overflows"
    return y


class _Book:
    """A fixture being built: its canvas, its ground truth and its prose source."""

    def __init__(self, out_dir: Path, path: str, title: str, seed: int) -> None:
        pdf_path = out_dir / path
        pdf_path.parent.mkdir(parents=True, exist_ok=True)
        self.canvas = Canvas(
            str(pdf_path),
            pagesize=(PAGE_WIDTH, PAGE_HEIGHT),
            invariant=True,
            pageCompression=0,
            lang=LANGUAGE,
        )
        self.canvas.setTitle(title)
        self.title = title
        self.rng = random.Random(seed)
        self.truth: list[str] = []
        self.page = 0

    def _start(self, kind: str) -> None:
        self.page += 1
        self.truth.append(f"[page {self.page}: {kind}]")
        canvas = self.canvas
        canvas.setFont(HEADER_FONT, SMALL_SIZE)
        canvas.drawCentredString(PAGE_WIDTH / 2, HEADER_Y, self.title)
        canvas.setFont(BODY_FONT, SMALL_SIZE)
        canvas.drawCentredString(PAGE_WIDTH / 2, FOLIO_Y, str(self.page))

    def prose(self) -> None:
        self._start("prose")
        texts = [prose.paragraph(self.rng, 5, 7) for _ in range(4)]
        _paragraphs(self.canvas, texts, MARGIN_X, TEXT_WIDTH, TOP)
        self.truth.extend(texts)
        self.canvas.showPage()

    def two_column(self) -> None:
        self._start("two-column")
        for side, x in (("left", MARGIN_X), ("right", MARGIN_X + COLUMN_WIDTH + GUTTER)):
            texts = [prose.paragraph(self.rng, 6, 8) for _ in range(2)]
            _paragraphs(self.canvas, texts, x, COLUMN_WIDTH, TOP)
            self.truth.append(f"[{side}]")
            self.truth.extend(texts)
        self.canvas.showPage()

    def table(self) -> None:
        self._start("table")
        canvas = self.canvas
        text = prose.paragraph(self.rng, 2, 3)
        y = _paragraphs(canvas, [text], MARGIN_X, TEXT_WIDTH, TOP) - LEADING
        top = y + BODY_SIZE
        rows = [top - CELL_HEIGHT * i for i in range(len(TABLE) + 1)]
        canvas.grid(TABLE_COLUMNS, rows)
        canvas.setFont(BODY_FONT, BODY_SIZE)
        for row, cells in zip(rows, TABLE, strict=False):
            for x, cell in zip(TABLE_COLUMNS, cells, strict=False):
                canvas.drawString(x + 6, row - 14, cell)
        canvas.setFont(MATH_FONT, BODY_SIZE)
        canvas.drawCentredString(PAGE_WIDTH / 2, rows[-1] - 3 * LEADING, EQUATIONS[0])
        self.truth.append(text)
        self.truth.append("[table]")
        self.truth.append("\n".join(" | ".join(cells) for cells in TABLE))
        self.truth.append("[equation]")
        self.truth.append(EQUATIONS[0])
        canvas.showPage()

    def math(self) -> None:
        self._start("math")
        canvas = self.canvas
        text = prose.paragraph(self.rng, 2, 3)
        y = _paragraphs(canvas, [text], MARGIN_X, TEXT_WIDTH, TOP) - LEADING
        canvas.setFont(MATH_FONT, BODY_SIZE)
        for equation in EQUATIONS:
            y -= 2 * LEADING
            canvas.drawCentredString(PAGE_WIDTH / 2, y, equation)
        self.truth.append(text)
        self.truth.append("[equations]")
        self.truth.append("\n".join(EQUATIONS))
        canvas.showPage()

    def save(self, out_dir: Path, truth_path: str) -> None:
        self.canvas.save()
        (out_dir / truth_path).write_text("\n\n".join(self.truth) + "\n", encoding="utf-8")


def _build(out_dir: Path, path: str, truth: str, title: str, seed: int, kinds: str) -> None:
    """``kinds`` gives each page's kind by its initial: prose, two-column, table, math."""
    book = _Book(out_dir, path, title, seed)
    pages = {"p": book.prose, "c": book.two_column, "t": book.table, "m": book.math}
    for kind in kinds:
        pages[kind]()
    book.save(out_dir, truth)


def build_two_column(out_dir: Path) -> None:
    _build(out_dir, TWO_COLUMN, TWO_COLUMN_TRUTH, "Two Columns of the Coast", 38, "pccc")


def build_complex_page(out_dir: Path) -> None:
    _build(out_dir, COMPLEX_PAGE, COMPLEX_PAGE_TRUTH, "Sailing Tables", 39, "ptp")


def build_fallbacks(out_dir: Path) -> None:
    _build(out_dir, FALLBACKS, FALLBACKS_TRUTH, "A Mixed Almanac", 40, "pptpcpmp")


def build_complex_pages(out_dir: Path) -> None:
    _build(out_dir, COMPLEX_PAGES, COMPLEX_PAGES_TRUTH, "Tide Tables", 41, "pptpppmtmp")
