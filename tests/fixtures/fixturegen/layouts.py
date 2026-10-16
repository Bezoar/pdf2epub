"""Pages that can't be reflowed faithfully (RFL-R11, RFL-R13): the two-column set, the
table page and the math page, in four born-digital fixtures.

Every page is US Letter, with a centred running header (9 pt Times-Italic) and a centred
page number in the footer (9 pt), both of them furniture. Pages are of these kinds:

- **prose**: indented paragraphs of 10 pt Times-Roman across the full text width;
- **two-column**: two columns of prose, 243 pt wide with an 18 pt gutter, each holding
  two whole paragraphs; the centred header and page number cross the gutter;
- **titled**: a two-column page under a centred title block across both columns (a 16 pt
  title, two 11 pt lines of authors, two 9 pt lines of affiliation);
- **figured**: a two-column page over a figure across both columns: ten lines of 9 pt
  Courier code, each crossing the gutter, and a one-line caption;
- **listing**: one column: two paragraphs of prose across the full text width, then a
  listing of twelve lines of 9 pt Courier code, each with a comment beside it in 9 pt
  Courier (a narrow column of code and a wider one of comments, side by side);
- **table**: a short paragraph, then a ruled grid of 4 columns and 5 rows of cell text,
  then a displayed equation in Times-Italic;
- **math**: a short paragraph, then ten displayed equations in Times-Italic, made of
  single-letter variables and the operators ``=``, ``+``, ``<`` and the multiplication,
  division and plus-minus signs.

The fixtures (pages by kind):

- ``born-digital/two-column.pdf``: 1 prose, 2-4 two-column, 5 titled, 6 figured, 7 listing
  (RFL-AC8, EPUB-AC7, MAIN-AC-B);
- ``born-digital/complex-page.pdf``: 1 and 3 prose, 2 table with its equation (RFL-AC9);
- ``born-digital/fallbacks.pdf``: 3 table, 5 two-column, 7 math, the other 5 of its 8
  pages prose (API-AC8);
- ``born-digital/complex-pages.pdf``: 3 and 8 table, 7 and 9 math, the other 6 of its 10
  pages prose (CLI-AC14).

Each ground truth (``.txt`` beside the PDF) holds the pages in order, without furniture.
Each page starts with a line ``[page N: KIND]``; then, separated by blank lines, its
paragraphs on one line each; a two-column page (of any of the three kinds) has ``[left]``
and ``[right]`` lines before each column's paragraphs, and an ``[across]`` line before the
title block's or the figure's lines, one per line, where they are on the page; a listing
page gives its listing after ``[listing]``, one line of code and comment per line; a table
page gives its rows as cell texts separated by `` | `` after a ``[table]`` line, then its
equation after ``[equation]``; a math page gives its equations after ``[equations]``, one
per line.
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
TITLE_BLOCK = [
    ("Times-Bold", 16.0, "Notes on the Northern Coast"),
    ("Times-Roman", 11.0, "Ada Fenwick, Tomas Reyes and Mira Holt"),
    ("Times-Roman", 11.0, "with drawings by Elias Brandt"),
    ("Times-Italic", SMALL_SIZE, "Harbour Survey Office, Port Ellen"),
    ("Times-Italic", SMALL_SIZE, "survey office at the old customs house"),
]
CODE_FONT, CODE_LEADING = "Courier", 11.0
CODE = [
    "for station in survey.stations: station.record(high_tide, low_tide, wind)",
    "    if station.depth < shallow_limit: mark_channel(station, warning=True)",
    "    reading = station.gauge.read(minutes=15) and station.gauge.reset()",
    "    tides.append((station.name, reading.height, reading.time_of_day))",
    "    if reading.height > storm_limit: send_signal(lighthouse, reading)",
    "for name, height, time in sorted(tides): print(name, height, time)",
    "    chart.plot(name, height, colour=depth_colour(height), label=time)",
    "    if height == max_height: chart.annotate(name, 'highest of the day')",
    "    harbour.log.write(name + ' ' + str(height) + ' at ' + str(time))",
    "chart.save('northern-coast-tides.pdf') and harbour.log.close()",
]
LISTING = [
    ("v0 := ld state[748]", "load the gauge readings from the record"),
    ("st sp[0], v0", "store the readings to the station stack"),
    ("v1 := ld state[764]", "load the tide count from the record"),
    ("v2 := i2f(v1)", "convert the count from integer to float"),
    ("st sp[8], v1", "store the count to the station stack"),
    ("v3 := ld v0[4]", "load the class word for the readings"),
    ("v4 := and v3, -4", "mask out the class tag of the readings"),
    ("v5 := eq v4, Array", "test whether the readings are a list"),
    ("xf v5", "leave the trace if the readings are not"),
    ("v6 := set(v0, v2)", "call the function that sets the entry"),
    ("v7 := eq v6, 0", "test the value the call returned"),
    ("xt v7", "leave the trace if the call failed"),
]
LISTING_COMMENT_X = MARGIN_X + 140
CAPTION = "Figure 1. The program that records and charts the tides at each survey station."

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
        self._columns(TOP)
        self.canvas.showPage()

    def _columns(self, top: float) -> float:
        """Two columns of two paragraphs from ``top``; the lower column's end."""
        ends = []
        for side, x in (("left", MARGIN_X), ("right", MARGIN_X + COLUMN_WIDTH + GUTTER)):
            texts = [prose.paragraph(self.rng, 6, 8) for _ in range(2)]
            ends.append(_paragraphs(self.canvas, texts, x, COLUMN_WIDTH, top))
            self.truth.append(f"[{side}]")
            self.truth.extend(texts)
        return min(ends)

    def titled(self) -> None:
        self._start("titled")
        y = TOP
        for font, size, text in TITLE_BLOCK:
            self.canvas.setFont(font, size)
            self.canvas.drawCentredString(PAGE_WIDTH / 2, y, text)
            y -= size * 1.5
        self.truth.append("[across]")
        self.truth.append("\n".join(text for _, _, text in TITLE_BLOCK))
        self._columns(y - LEADING)
        self.canvas.showPage()

    def figured(self) -> None:
        self._start("figured")
        canvas = self.canvas
        y = self._columns(TOP) - 2 * LEADING
        canvas.setFont(CODE_FONT, SMALL_SIZE)
        for line in CODE:
            assert MARGIN_X + stringWidth(line, CODE_FONT, SMALL_SIZE) > PAGE_WIDTH / 2 + GUTTER
            canvas.drawString(MARGIN_X, y, line)
            y -= CODE_LEADING
        canvas.setFont(BODY_FONT, SMALL_SIZE)
        canvas.drawString(MARGIN_X, y - CODE_LEADING, CAPTION)
        assert y - CODE_LEADING > BOTTOM, "page overflows"
        self.truth.append("[across]")
        self.truth.append("\n".join([*CODE, CAPTION]))
        canvas.showPage()

    def listing(self) -> None:
        self._start("listing")
        canvas = self.canvas
        texts = [prose.paragraph(self.rng, 5, 7) for _ in range(2)]
        y = _paragraphs(canvas, texts, MARGIN_X, TEXT_WIDTH, TOP) - LEADING
        canvas.setFont(CODE_FONT, SMALL_SIZE)
        for code, comment in LISTING:
            canvas.drawString(MARGIN_X, y, code)
            canvas.drawString(LISTING_COMMENT_X, y, f"// {comment}")
            y -= CODE_LEADING
        assert y > BOTTOM, "page overflows"
        self.truth.extend(texts)
        self.truth.append("[listing]")
        self.truth.append("\n".join(f"{code} // {comment}" for code, comment in LISTING))
        canvas.showPage()

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
    """``kinds`` gives each page's kind by its initial: prose, two-column, titled (h),
    figured, listing, table, math."""
    book = _Book(out_dir, path, title, seed)
    pages = {
        "p": book.prose,
        "c": book.two_column,
        "h": book.titled,
        "f": book.figured,
        "l": book.listing,
        "t": book.table,
        "m": book.math,
    }
    for kind in kinds:
        pages[kind]()
    book.save(out_dir, truth)


def build_two_column(out_dir: Path) -> None:
    _build(out_dir, TWO_COLUMN, TWO_COLUMN_TRUTH, "Two Columns of the Coast", 38, "pccchfl")


def build_complex_page(out_dir: Path) -> None:
    _build(out_dir, COMPLEX_PAGE, COMPLEX_PAGE_TRUTH, "Sailing Tables", 39, "ptp")


def build_fallbacks(out_dir: Path) -> None:
    _build(out_dir, FALLBACKS, FALLBACKS_TRUTH, "A Mixed Almanac", 40, "pptpcpmp")


def build_complex_pages(out_dir: Path) -> None:
    _build(out_dir, COMPLEX_PAGES, COMPLEX_PAGES_TRUTH, "Tide Tables", 41, "pptpppmtmp")
