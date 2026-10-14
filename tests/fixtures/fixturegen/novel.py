"""The born-digital novel fixture (TST-R3): ``born-digital/novel.pdf``.

A single-column, 40-page novel of 10 chapters, 4 pages each, typeset with ReportLab:

- a PDF outline of 12 entries: the 10 chapter titles, two of which (chapters 2 and 7)
  have one nested section entry;
- page labels ``1``-``40``, a centred page number in every footer, and a running header
  on every page except chapter openers: the book title on even pages, the chapter title
  on odd pages;
- 24 pt bold chapter titles, 14 pt bold section titles, 11 pt body text with indented
  paragraphs;
- paragraphs split across pages (at least one page break falls mid-sentence, so the next
  page starts in lowercase, and at least one page ends with a full stop before an
  indented paragraph), and hyphenated line ends (``exam-`` / ``ple``).

The ground truth, ``born-digital/novel.txt``, is the book's text without furniture:
chapter titles, section titles and paragraphs, each on one line, separated by blank
lines, with no hyphenation.
"""

import random
from dataclasses import dataclass, field
from pathlib import Path

from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen.canvas import Canvas

from fixturegen import prose

PATH = "born-digital/novel.pdf"
GROUND_TRUTH = "born-digital/novel.txt"

BOOK_TITLE = "The Lantern Coast"
AUTHOR = "Ada Quill"
LANGUAGE = "en"
CHAPTER_TITLES = [
    "The Harbour",
    "A Letter from the Mainland",
    "Fog",
    "The Keeper's Notebook",
    "Low Tide",
    "The Schoolteacher",
    "Lamps and Mirrors",
    "The Storm",
    "Afterwards",
    "The Last Light",
]
# Chapter index (0-based) -> the title of its one nested section.
SECTIONS = {1: "What the Letter Said", 6: "The Night Crossing"}
PAGES_PER_CHAPTER = 4
SEED = 1906

PAGE_WIDTH, PAGE_HEIGHT = 432.0, 648.0  # 6 x 9 in
MARGIN_X = 54.0
BODY_TOP, BODY_BOTTOM = 576.0, 72.0
TEXT_WIDTH = PAGE_WIDTH - 2 * MARGIN_X
BODY_FONT, BODY_SIZE, LEADING = "Times-Roman", 11.0, 14.5
INDENT = 18.0
CHAPTER_FONT, CHAPTER_SIZE = "Times-Bold", 24.0
SECTION_FONT, SECTION_SIZE = "Times-Bold", 14.0
HEADER_FONT, HEADER_SIZE, HEADER_Y = "Times-Italic", 9.0, 612.0
FOOTER_FONT, FOOTER_SIZE, FOOTER_Y = "Times-Roman", 9.0, 40.0

# Body line slots: a normal page, and a chapter opener (the title takes the top lines).
OPENER_SKIP = 4
SLOTS = int((BODY_TOP - BODY_BOTTOM - BODY_SIZE) // LEADING) + 1
SECTION_SLOTS = 3  # blank line, the section title, blank line
MIN_HYPHEN_WORD, MIN_PREFIX, MIN_SUFFIX = 8, 4, 3


@dataclass
class Line:
    text: str
    first: bool  # first line of its paragraph (indented)
    last: bool  # last line of its paragraph


@dataclass
class Section:
    title: str


@dataclass
class Page:
    chapter: int
    opener: bool
    items: list[Line | Section] = field(default_factory=list)


def _fits(text: str, width: float) -> bool:
    return bool(stringWidth(text, BODY_FONT, BODY_SIZE) <= width)


def break_lines(text: str) -> list[Line]:
    """Greedy line breaking, hyphenating a long word that would not fit."""
    lines: list[Line] = []
    current: list[str] = []
    words = text.split()
    i = 0
    while i < len(words):
        word = words[i]
        width = TEXT_WIDTH - (INDENT if not lines else 0)
        candidate = " ".join([*current, word])
        if _fits(candidate, width):
            current.append(word)
            i += 1
            continue
        letters = len(word.rstrip(".,"))
        if current and word.isascii() and letters >= MIN_HYPHEN_WORD:
            for cut in range(letters - MIN_SUFFIX, MIN_PREFIX - 1, -1):
                head = word[:cut] + "-"
                if _fits(" ".join([*current, head]), width):
                    current.append(head)
                    words[i] = word[cut:]
                    break
        lines.append(Line(" ".join(current), first=not lines, last=False))
        current = []
    lines.append(Line(" ".join(current), first=not lines, last=True))
    return lines


def paginate(chapter: int, blocks: list[str | Section]) -> list[Page]:
    """Lay a chapter's blocks out on pages, keeping at least two lines of a paragraph
    (and a section title with two lines after it) together at a page bottom."""
    pages = [Page(chapter, opener=True)]
    used = OPENER_SKIP

    def new_page() -> None:
        nonlocal used
        pages.append(Page(chapter, opener=False))
        used = 0

    for block in blocks:
        if isinstance(block, Section):
            if used + SECTION_SLOTS + 2 > SLOTS:
                new_page()
            pages[-1].items.append(block)
            used += SECTION_SLOTS
            continue
        lines = break_lines(block)
        if used + min(2, len(lines)) > SLOTS:
            new_page()
        for line in lines:
            if used == SLOTS:
                new_page()
            pages[-1].items.append(line)
            used += 1
    return pages


def build_chapters() -> tuple[list[list[str | Section]], list[Page]]:
    """Each chapter's blocks, grown paragraph by paragraph until it fills its pages."""
    rng = random.Random(SEED)
    chapters: list[list[str | Section]] = []
    pages: list[Page] = []
    for index in range(len(CHAPTER_TITLES)):
        blocks: list[str | Section] = []
        while True:
            if index in SECTIONS and len(blocks) == 3:
                blocks.append(Section(SECTIONS[index]))
            trial = [*blocks, prose.paragraph(rng)]
            if len(paginate(index, trial)) > PAGES_PER_CHAPTER:
                break
            blocks = trial
        laid_out = paginate(index, blocks)
        assert len(laid_out) == PAGES_PER_CHAPTER, (index, len(laid_out))
        chapters.append(blocks)
        pages.extend(laid_out)
    return chapters, pages


def _check_properties(pages: list[Page]) -> None:
    """Assert the layout features the fixture promises are really there."""
    lines = [[i for i in page.items if isinstance(i, Line)] for page in pages]
    mid_sentence_join = clean_page_end = False
    for n in range(len(pages) - 1):
        here, there = lines[n], lines[n + 1]
        if not here or not there or pages[n + 1].opener:
            continue
        end, start = here[-1], there[0]
        if not end.last and start.text[:1].islower() and not end.text.endswith((".", "-")):
            mid_sentence_join = True
        if end.last and end.text.endswith(".") and start.first:
            clean_page_end = True
    hyphenated = any(line.text.endswith("-") for page in lines for line in page)
    assert len(pages) == PAGES_PER_CHAPTER * len(CHAPTER_TITLES)
    assert mid_sentence_join, "no page break falls mid-sentence"
    assert clean_page_end, "no page ends with a full stop before an indented paragraph"
    assert hyphenated, "no line end is hyphenated"


def _centred(canvas: Canvas, text: str, font: str, size: float, y: float) -> None:
    canvas.setFont(font, size)
    canvas.drawCentredString(PAGE_WIDTH / 2, y, text)


def build(out_dir: Path) -> None:
    chapters, pages = build_chapters()
    _check_properties(pages)

    pdf_path = out_dir / PATH
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    canvas = Canvas(
        str(pdf_path),
        pagesize=(PAGE_WIDTH, PAGE_HEIGHT),
        invariant=True,
        pageCompression=0,
        lang=LANGUAGE,
    )
    canvas.setTitle(BOOK_TITLE)
    canvas.setAuthor(AUTHOR)
    canvas.addPageLabel(0, "ARABIC", 1)

    for number, page in enumerate(pages, start=1):
        chapter_title = CHAPTER_TITLES[page.chapter]
        y = BODY_TOP - BODY_SIZE
        if page.opener:
            key = f"chapter-{page.chapter + 1}"
            canvas.bookmarkPage(key)
            canvas.addOutlineEntry(chapter_title, key, level=0)
            canvas.setFont(CHAPTER_FONT, CHAPTER_SIZE)
            canvas.drawString(MARGIN_X, BODY_TOP - CHAPTER_SIZE, chapter_title)
            y -= OPENER_SKIP * LEADING
        else:
            header = BOOK_TITLE if number % 2 == 0 else chapter_title
            _centred(canvas, header, HEADER_FONT, HEADER_SIZE, HEADER_Y)
        for item in page.items:
            if isinstance(item, Section):
                key = f"section-{page.chapter + 1}"
                y -= LEADING
                canvas.bookmarkPage(key, fit="XYZ", top=y + SECTION_SIZE)
                canvas.addOutlineEntry(item.title, key, level=1)
                canvas.setFont(SECTION_FONT, SECTION_SIZE)
                canvas.drawString(MARGIN_X, y, item.title)
                y -= 2 * LEADING
                continue
            canvas.setFont(BODY_FONT, BODY_SIZE)
            canvas.drawString(MARGIN_X + (INDENT if item.first else 0), y, item.text)
            y -= LEADING
        _centred(canvas, str(number), FOOTER_FONT, FOOTER_SIZE, FOOTER_Y)
        canvas.showPage()
    canvas.save()

    text: list[str] = []
    for title, blocks in zip(CHAPTER_TITLES, chapters, strict=True):
        text.append(title)
        text.extend(b.title if isinstance(b, Section) else b for b in blocks)
    (out_dir / GROUND_TRUTH).write_text("\n\n".join(text) + "\n", encoding="utf-8")
