"""The two-page book (RFL-R16 in a very short book): ``born-digital/two-pages.pdf``.

Two pages, each with the running header ``The Short Crossing`` at the top in 9 pt
Times-Italic, one English paragraph in 11 pt Times-Roman, and its printed page number
(``1``, ``2``) centred in the footer in 9 pt. Each paragraph ends its page with a full
stop, so the two stay separate.

The ground truth, ``born-digital/two-pages.txt``, is the two paragraphs without the
header or the page numbers.
"""

from pathlib import Path

from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen.canvas import Canvas

PATH = "born-digital/two-pages.pdf"
GROUND_TRUTH = "born-digital/two-pages.txt"

TITLE = "The Short Crossing"
LANGUAGE = "en"
HEADER = TITLE
BODY_FONT, HEADER_FONT = "Times-Roman", "Times-Italic"
BODY_SIZE, SMALL_SIZE, LEADING = 11.0, 9.0, 14.5
PAGE_WIDTH, PAGE_HEIGHT = 432.0, 648.0
MARGIN_X, HEADER_Y, BODY_TOP, FOLIO_Y, INDENT = 54.0, 600.0, 560.0, 40.0, 18.0

PAGES = [
    [
        "The ferry left the harbour before dawn, its deck still wet from the",
        "night rain, and the few passengers stood along the rail to watch the lights",
        "of the town grow small behind them while the gulls followed in the",
        "wake.",
    ],
    [
        "By noon the far shore had come into view, a low green line under a",
        "pale sky, and the captain sounded the horn twice as the boat turned",
        "toward the narrow channel that led into the sheltered bay on the northern",
        "side.",
    ],
]


def build(out_dir: Path) -> None:
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
    for number, lines in enumerate(PAGES, start=1):
        canvas.setFont(HEADER_FONT, SMALL_SIZE)
        canvas.drawCentredString(PAGE_WIDTH / 2, HEADER_Y, HEADER)
        canvas.setFont(BODY_FONT, BODY_SIZE)
        y = BODY_TOP
        for index, line in enumerate(lines):
            width = PAGE_WIDTH - 2 * MARGIN_X - (INDENT if index == 0 else 0)
            assert stringWidth(line, BODY_FONT, BODY_SIZE) <= width
            canvas.drawString(MARGIN_X + (INDENT if index == 0 else 0), y, line)
            y -= LEADING
        canvas.setFont(BODY_FONT, SMALL_SIZE)
        canvas.drawCentredString(PAGE_WIDTH / 2, FOLIO_Y, str(number))
        canvas.showPage()
    canvas.save()

    text = "\n\n".join(" ".join(lines) for lines in PAGES)
    (out_dir / GROUND_TRUTH).write_text(text + "\n", encoding="utf-8")
