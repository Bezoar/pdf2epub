"""The heading and emphasis sample (RFL-AC13, EPUB-AC5): ``born-digital/headings.pdf``.

Two pages, typeset with ReportLab in the standard Times fonts, with page labels ``H-1``
and ``H-2``:

- two 24 pt bold chapter titles (one opening each page) and three 14 pt bold section
  titles, on 11 pt body text;
- body paragraphs with italic words (Times-Italic) and bold words (Times-Bold) inside
  their lines;
- on page 1, a figure with a 9 pt caption directly below it; on page 2, a figure with no
  caption. Both are small RGB inline images whose pixels are written as hexadecimal, so
  the file does not depend on the zlib build (TST-R1).

The ground truth, ``born-digital/headings.txt``, is the text in reading order, one title
or paragraph per entry, separated by blank lines, with the emphasis marked as
``*italic*`` and ``**bold**``, and the caption as ``[Figure: <caption>]``.
"""

from pathlib import Path

from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen.canvas import Canvas

PATH = "born-digital/headings.pdf"
GROUND_TRUTH = "born-digital/headings.txt"

TITLE = "Headings and Emphasis"
PAGE_WIDTH, PAGE_HEIGHT = 432.0, 648.0
MARGIN_X, TOP = 54.0, 590.0
TEXT_WIDTH = PAGE_WIDTH - 2 * MARGIN_X
BODY, ITALIC, BOLD = "Times-Roman", "Times-Italic", "Times-Bold"
BODY_SIZE, LEADING, INDENT = 11.0, 14.5, 18.0
CHAPTER_SIZE, SECTION_SIZE, CAPTION_SIZE = 24.0, 14.0, 9.0
FIGURE_WIDTH, FIGURE_HEIGHT = 160.0, 80.0
CAPTION = "The harbour wall at low tide, seen from the lighthouse."

# A paragraph is a list of (text, style) runs; style is "", "i" or "b".
Run = tuple[str, str]
PAGES: list[list[tuple[str, object]]] = [
    [
        ("chapter", "The First Chapter"),
        (
            "para",
            [
                ("The keeper climbed the stairs every evening and lit the ", ""),
                ("great", "i"),
                (
                    " lamp before the fishing boats came home. He kept a careful record of "
                    "the weather in a notebook that he called the ",
                    "",
                ),
                ("Ledger", "b"),
                (", and nobody else was allowed to read it.", ""),
            ],
        ),
        ("section", "The Ledger"),
        (
            "para",
            [
                ("Its pages were full of small, neat handwriting. Some entries were ", ""),
                ("underlined twice", "i"),
                (", and one of them, from a winter long ago, was marked ", ""),
                ("urgent", "b"),
                (" in red ink beside the date.", ""),
            ],
        ),
        ("figure", CAPTION),
        ("section", "The Winter Entry"),
        (
            "para",
            [
                (
                    "Nobody in the village could explain what had happened that winter, "
                    "although everyone had a story about it.",
                    "",
                ),
            ],
        ),
    ],
    [
        ("chapter", "The Second Chapter"),
        (
            "para",
            [
                ("In the spring the schoolteacher asked to see the notebook. The keeper said ", ""),
                ("no", "b"),
                (" at first, but he changed his mind after she told him about the ", ""),
                ("Mariner", "i"),
                (", a ship her grandfather had sailed on.", ""),
            ],
        ),
        ("figure", None),
        ("section", "What They Found"),
        (
            "para",
            [
                (
                    "Together they read the winter entry again, slowly, and this time the "
                    "words made sense to both of them.",
                    "",
                ),
            ],
        ),
    ],
]
FONTS = {"": BODY, "i": ITALIC, "b": BOLD}
MARKS = {"": "", "i": "*", "b": "**"}


def _words(runs: list[Run]) -> list[tuple[str, str, bool]]:
    """The paragraph's words with their styles; the flag says a space comes before it."""
    words: list[tuple[str, str, bool]] = []
    space = False
    for text, style in runs:
        for i, word in enumerate(text.split(" ")):
            if i > 0:
                space = True
            if word:
                words.append((word, style, space))
                space = False
    return words


def _lines(runs: list[Run]) -> list[list[tuple[str, str]]]:
    """Greedy line breaking; each line is a list of (text, style) pieces."""
    lines: list[list[tuple[str, str]]] = [[]]
    width = INDENT
    for word, style, space in _words(runs):
        piece = (" " if space else "") + word
        w = stringWidth(piece, FONTS[style], BODY_SIZE)
        if lines[-1] and space and width + w > TEXT_WIDTH:
            lines.append([])
            width = 0.0
            piece, w = word, stringWidth(word, FONTS[style], BODY_SIZE)
        lines[-1].append((piece, style))
        width += w
    return lines


def _image(canvas: Canvas, x: float, y: float, shade: int) -> None:
    """A 16 x 8 RGB inline image, hex-encoded, drawn FIGURE_WIDTH wide at (x, y)."""
    pixels = bytearray()
    for row in range(8):
        for column in range(16):
            pixels += bytes((shade, (column * 16) % 256, (row * 32) % 256))
    data = pixels.hex() + ">"
    canvas._code.append(  # ReportLab has no uncompressed image API; raw operators do it
        f"q {FIGURE_WIDTH} 0 0 {FIGURE_HEIGHT} {x} {y} cm "
        f"BI /W 16 /H 8 /BPC 8 /CS /RGB /F /AHx ID {data} EI Q"
    )


def build(out_dir: Path) -> None:
    pdf_path = out_dir / PATH
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    canvas = Canvas(
        str(pdf_path),
        pagesize=(PAGE_WIDTH, PAGE_HEIGHT),
        invariant=True,
        pageCompression=0,
        lang="en",
    )
    canvas.setTitle(TITLE)
    canvas.addPageLabel(0, "ARABIC", 1, prefix="H-")
    truth: list[str] = []
    shade = 40
    for page in PAGES:
        y = TOP
        for kind, content in page:
            if kind == "chapter":
                assert isinstance(content, str)
                y -= CHAPTER_SIZE
                canvas.setFont(BOLD, CHAPTER_SIZE)
                canvas.drawString(MARGIN_X, y, content)
                y -= 2 * LEADING
                truth.append(content)
            elif kind == "section":
                assert isinstance(content, str)
                y -= LEADING
                canvas.setFont(BOLD, SECTION_SIZE)
                canvas.drawString(MARGIN_X, y, content)
                y -= 2 * LEADING
                truth.append(content)
            elif kind == "para":
                assert isinstance(content, list)
                for n, line in enumerate(_lines(content)):
                    x = MARGIN_X + (INDENT if n == 0 else 0)
                    for piece, style in line:
                        canvas.setFont(FONTS[style], BODY_SIZE)
                        canvas.drawString(x, y, piece)
                        x += stringWidth(piece, FONTS[style], BODY_SIZE)
                    y -= LEADING
                truth.append("".join(f"{MARKS[s]}{t}{MARKS[s]}" for t, s in content))
            else:
                y -= LEADING + FIGURE_HEIGHT
                _image(canvas, MARGIN_X + 40, y, shade)
                shade += 120
                if content is not None:
                    y -= CAPTION_SIZE + 4
                    canvas.setFont(BODY, CAPTION_SIZE)
                    canvas.drawString(MARGIN_X + 40, y, str(content))
                    truth.append(f"[Figure: {content}]")
                y -= 2 * LEADING
        canvas.showPage()
    canvas.save()
    (out_dir / GROUND_TRUTH).write_text("\n\n".join(truth) + "\n", encoding="utf-8")
