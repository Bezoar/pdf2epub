"""The verse-and-code sample (RFL-AC25, RFL-AC27): ``born-digital/verse-and-code.pdf``.

Two single-column pages, set with ReportLab's standard fonts:

- page 1: an indented prose paragraph; a poem of three four-line stanzas, set in body type
  36 pt in from the margin with a blank line between stanzas, whose lines end well short
  of the column's right edge and mostly start in lowercase; a second prose paragraph; then
  the start of a Courier code block, running to the foot of the page;
- page 2: the rest of the code block, from the top of the page, then a last prose
  paragraph.

The code's comment lines end in hyphens that a prose paragraph would de-hyphenate with the
English wordlist (``exam-`` / ``ine``, ``re-`` / ``pair``); its lines are indented with
spaces in the text layer; and the last line of page 1 ends in a hyphen while page 2 starts
at the margin, so a prose-style page join would fire.

The ground truth, ``born-digital/verse-and-code.txt``, holds one entry per block,
separated by blank lines: the prose paragraphs on one line each, and each stanza and each
page's part of the code block with its source lines on separate lines (the code with its
leading spaces).
"""

import random
from pathlib import Path

from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen.canvas import Canvas

from fixturegen import prose

PATH = "born-digital/verse-and-code.pdf"
GROUND_TRUTH = "born-digital/verse-and-code.txt"

TITLE = "Verse and Code Sample"
LANGUAGE = "en"
SEED = 52

PAGE_WIDTH, PAGE_HEIGHT = 432.0, 648.0
MARGIN_X, TOP, BOTTOM = 54.0, 576.0, 72.0
TEXT_WIDTH = PAGE_WIDTH - 2 * MARGIN_X
BODY_FONT, BODY_SIZE, LEADING = "Times-Roman", 11.0, 14.5
INDENT, POEM_INSET = 18.0, 36.0
CODE_FONT, CODE_SIZE, CODE_LEADING = "Courier", 10.0, 12.0

STANZAS = [
    [
        "The lamp is lit above the bay,",
        "the boats come slowly in;",
        "the keeper climbs the winding stair",
        "to where the lights begin.",
    ],
    [
        "The fog rolls up across the stones,",
        "the gulls have gone to ground;",
        "the mirror turns, the shutters close,",
        "the harbour makes no sound.",
    ],
    [
        "And when the morning finds the coast",
        "the lamp is dark once more;",
        "the keeper sleeps, the boats go out,",
        "the tide comes to the shore.",
    ],
]
CODE_PAGE_1 = [
    "def light_the_lamp(keeper):",
    "    # Trim the wick, then exam-",
    "    # ine the glass for well-",
    "    # known cracks and re-",
]
CODE_PAGE_2 = [
    "    # pair them before dusk.",
    "    if keeper.oil < 3:",
    '        keeper.fetch("oil")',
    "    keeper.light()",
]


def _wrap(text: str) -> list[str]:
    """Greedy line breaking at spaces, with the first line indented."""
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


def _prose(canvas: Canvas, text: str, y: float) -> float:
    canvas.setFont(BODY_FONT, BODY_SIZE)
    for index, line in enumerate(_wrap(text)):
        canvas.drawString(MARGIN_X + (INDENT if index == 0 else 0), y, line)
        y -= LEADING
    return y


def _code(canvas: Canvas, lines: list[str], y: float) -> float:
    canvas.setFont(CODE_FONT, CODE_SIZE)
    for line in lines:
        canvas.drawString(MARGIN_X, y, line)
        y -= CODE_LEADING
    return y


def build(out_dir: Path) -> None:
    rng = random.Random(SEED)
    paragraphs = [prose.paragraph(rng, 4, 5) for _ in range(3)]

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

    y = _prose(canvas, paragraphs[0], TOP) - LEADING
    canvas.setFont(BODY_FONT, BODY_SIZE)
    for stanza in STANZAS:
        for line in stanza:
            canvas.drawString(MARGIN_X + POEM_INSET, y, line)
            y -= LEADING
        y -= LEADING
    y = _prose(canvas, paragraphs[1], y) - LEADING
    # The code block's first part runs to the foot of page 1.
    code_top = BOTTOM + (len(CODE_PAGE_1) - 1) * CODE_LEADING
    assert y > code_top + LEADING, "page 1 overflows"
    _code(canvas, CODE_PAGE_1, code_top)
    canvas.showPage()

    y = _code(canvas, CODE_PAGE_2, TOP) - LEADING
    _prose(canvas, paragraphs[2], y)
    canvas.showPage()
    canvas.save()

    entries = [
        paragraphs[0],
        *("\n".join(stanza) for stanza in STANZAS),
        paragraphs[1],
        "\n".join(CODE_PAGE_1),
        "\n".join(CODE_PAGE_2),
        paragraphs[2],
    ]
    (out_dir / GROUND_TRUTH).write_text("\n\n".join(entries) + "\n", encoding="utf-8")
