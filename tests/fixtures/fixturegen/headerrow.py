"""The header-row book (RFL-R16, #96): ``born-digital/header-row.pdf``.

Laid out like an OpenOffice export of a novel: six 5.5 x 8.5 in pages, each with one
running-header row at the top, in 10 pt Times-Roman: the author's name at the left
margin, the printed page number centred, and the book's title set flush right, as three
separate pieces of text on one baseline. There is no footer. Below the header, one
English paragraph per page in 12 pt Times-Roman, first line indented, ending with a full
stop so the pages stay separate paragraphs.

The ground truth, ``born-digital/header-row.txt``, is the six paragraphs without the
header row.
"""

import random
from pathlib import Path

from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen.canvas import Canvas

from fixturegen import prose

PATH = "born-digital/header-row.pdf"
GROUND_TRUTH = "born-digital/header-row.txt"

TITLE = "Lanternfall"
AUTHOR = "Ada Marsh"
LANGUAGE = "en"
PAGES = 6
SEED = 96
FONT, BODY_SIZE, HEADER_SIZE, LEADING = "Times-Roman", 12.0, 10.0, 13.7
PAGE_WIDTH, PAGE_HEIGHT = 396.0, 612.0
MARGIN_X, HEADER_Y, BODY_TOP, INDENT = 36.0, 567.0, 540.0, 11.0
TEXT_WIDTH = PAGE_WIDTH - 2 * MARGIN_X


def _break_lines(text: str) -> list[str]:
    lines: list[str] = []
    current: list[str] = []
    for word in text.split():
        width = TEXT_WIDTH - (INDENT if not lines else 0)
        if current and stringWidth(" ".join([*current, word]), FONT, BODY_SIZE) > width:
            lines.append(" ".join(current))
            current = []
        current.append(word)
    lines.append(" ".join(current))
    return lines


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
    canvas.setAuthor(AUTHOR)
    rng = random.Random(SEED)
    paragraphs = [prose.paragraph(rng, 8, 12) for _ in range(PAGES)]
    for number, text in enumerate(paragraphs, start=1):
        canvas.setFont(FONT, HEADER_SIZE)
        canvas.drawString(MARGIN_X, HEADER_Y, AUTHOR)
        canvas.drawCentredString(PAGE_WIDTH / 2, HEADER_Y, str(number))
        canvas.drawRightString(PAGE_WIDTH - MARGIN_X, HEADER_Y, TITLE)
        canvas.setFont(FONT, BODY_SIZE)
        y = BODY_TOP
        for index, line in enumerate(_break_lines(text)):
            canvas.drawString(MARGIN_X + (INDENT if index == 0 else 0), y, line)
            y -= LEADING
        assert y > 36.0, "a paragraph must fit on its page"
        canvas.showPage()
    canvas.save()

    (out_dir / GROUND_TRUTH).write_text("\n\n".join(paragraphs) + "\n", encoding="utf-8")
