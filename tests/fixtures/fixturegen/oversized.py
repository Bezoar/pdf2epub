"""The oversized single-chapter sample (EPUB-AC6): ``born-digital/oversized.pdf``.

One chapter of about 950 KB of plain English prose, with no headings, no outline and no
running headers, set in 6 pt Times on large pages (so the file stays small enough to
convert quickly). Paragraphs have indented first lines, at least two lines each (a
one-line paragraph that fills its line reads as part of the next), and no hyphenation.

The ground truth, ``born-digital/oversized.txt``, is the paragraphs, one per entry,
separated by blank lines.
"""

import random
from pathlib import Path

from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen.canvas import Canvas

from fixturegen import prose

PATH = "born-digital/oversized.pdf"
GROUND_TRUTH = "born-digital/oversized.txt"

TITLE = "One Long Chapter"
TEXT_BYTES = 950_000
SEED = 2024
PAGE_WIDTH, PAGE_HEIGHT = 1200.0, 1600.0
MARGIN = 50.0
FONT, SIZE, LEADING, INDENT = "Times-Roman", 6.0, 7.5, 18.0
TEXT_WIDTH = PAGE_WIDTH - 2 * MARGIN


def _lines(text: str) -> list[str]:
    lines: list[str] = []
    current: list[str] = []
    width = INDENT
    space = stringWidth(" ", FONT, SIZE)
    for word in text.split():
        w = stringWidth(word, FONT, SIZE)
        if current and width + space + w > TEXT_WIDTH:
            lines.append(" ".join(current))
            current, width = [], 0.0
        width += (space if current else 0.0) + w
        current.append(word)
    lines.append(" ".join(current))
    return lines


def build(out_dir: Path) -> None:
    rng = random.Random(SEED)
    paragraphs: list[str] = []
    size = 0
    while size < TEXT_BYTES:
        paragraph = prose.paragraph(rng, 6, 12)
        if len(_lines(paragraph)) < 2:
            continue
        paragraphs.append(paragraph)
        size += len(paragraph.encode("utf-8"))

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
    canvas.setFont(FONT, SIZE)
    y = PAGE_HEIGHT - MARGIN
    for paragraph in paragraphs:
        for n, line in enumerate(_lines(paragraph)):
            if y < MARGIN:
                canvas.showPage()
                canvas.setFont(FONT, SIZE)
                y = PAGE_HEIGHT - MARGIN
            canvas.drawString(MARGIN + (INDENT if n == 0 else 0), y, line)
            y -= LEADING
    canvas.showPage()
    canvas.save()
    (out_dir / GROUND_TRUTH).write_text("\n\n".join(paragraphs) + "\n", encoding="utf-8")
