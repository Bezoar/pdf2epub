"""Layout analysis of single-column pages (RFL-R10, RFL-R12 in part): lines into blocks by
vertical spacing and size, and blocks into paragraphs at first-line indents.

The measures that the whole document shares (body size, usual line gap, left margin) are
taken once, as a ``Typography``, from every page's lines.
"""

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from itertools import pairwise

from pdf2epub.reflow.extract import Line, PageText

# A gap between two lines wider than this many usual line gaps (or this share of the font
# size, whichever is larger) starts a new block.
_GAP_FACTOR, _GAP_MIN_EM = 1.5, 0.6
# Two lines whose sizes differ by more than this share are in different blocks.
_SIZE_TOLERANCE = 0.15
# A line is indented when it starts at least this many ems right of the left margin.
_INDENT_EM = 0.8
# A line ending at least this many ems left of its block's right edge ends short.
_SHORT_EM = 2.0
# Text this much larger than body text is display type (a title or heading).
_DISPLAY = 1.15


@dataclass(frozen=True)
class Typography:
    """Document-wide measures of the body text."""

    body_size: float
    """The most common character size, weighted by character count (RFL-R20)."""
    line_gap: float
    """The most common gap between consecutive body lines."""
    left: float
    """The most common left edge of body lines."""

    def is_display(self, size: float) -> bool:
        return size > self.body_size * _DISPLAY


@dataclass(frozen=True)
class TextBlock:
    """Lines set together: same size, no wider gap than usual between them."""

    lines: list[Line]

    @property
    def top(self) -> float:
        return self.lines[0].top

    @property
    def bottom(self) -> float:
        return self.lines[-1].bottom

    @property
    def size(self) -> float:
        return max(self.lines, key=lambda line: len(line.text)).size

    @property
    def text(self) -> str:
        return " ".join(line.text for line in self.lines)


@dataclass(frozen=True)
class DraftParagraph:
    """A paragraph's lines on one page, before joining and de-hyphenation."""

    lines: list[Line]
    indented: bool
    """Its first line is indented."""
    display: bool
    """It is set in display type (larger than body text)."""


def measure(pages: Iterable[PageText]) -> Typography:
    sizes: Counter[float] = Counter()
    lefts: Counter[float] = Counter()
    gaps: Counter[float] = Counter()
    lines_by_page = [page.lines for page in pages]
    for lines in lines_by_page:
        for line in lines:
            sizes[line.size] += len(line.text)
    body_size = sizes.most_common(1)[0][0] if sizes else 10.0
    for lines in lines_by_page:
        body = [line for line in lines if abs(line.size - body_size) <= 0.5]
        for line in body:
            lefts[round(line.x0)] += 1
        for above, below in pairwise(body):
            gaps[round(below.top - above.bottom, 1)] += 1
    left = lefts.most_common(1)[0][0] if lefts else 0.0
    line_gap = max(gaps.most_common(1)[0][0], 0.0) if gaps else 0.0
    return Typography(body_size=body_size, line_gap=line_gap, left=left)


def group_blocks(lines: list[Line], typography: Typography) -> list[TextBlock]:
    """Lines (top to bottom) grouped into blocks."""
    groups: list[list[Line]] = []
    for line in lines:
        if groups and _continues(groups[-1][-1], line, typography):
            groups[-1].append(line)
        else:
            groups.append([line])
    return [TextBlock(group) for group in groups]


def _continues(above: Line, below: Line, typography: Typography) -> bool:
    size = max(above.size, below.size)
    if abs(above.size - below.size) > _SIZE_TOLERANCE * size:
        return False
    if below.top < above.bottom and (below.x0 > above.x1 or below.x1 < above.x0):
        return False  # side by side on the same row, as in two columns
    limit = max(_GAP_FACTOR * typography.line_gap, _GAP_MIN_EM * size)
    return below.top - above.bottom <= limit


def paragraphs(block: TextBlock, typography: Typography) -> list[DraftParagraph]:
    """Split a block into paragraphs at indented lines. An indented line starts a paragraph
    when the line before it is not indented, or ends short of the block's right edge (so
    two one-line indented paragraphs stay apart, but an indented block quote stays whole).
    """
    left = min(typography.left, min(line.x0 for line in block.lines))
    right = max(line.x1 for line in block.lines)
    display = typography.is_display(block.size)

    def indented(line: Line) -> bool:
        return line.x0 - left >= _INDENT_EM * line.size

    def ends_short(line: Line) -> bool:
        return right - line.x1 >= _SHORT_EM * line.size

    groups: list[list[Line]] = []
    for i, line in enumerate(block.lines):
        above = block.lines[i - 1]
        if i == 0 or (indented(line) and (not indented(above) or ends_short(above))):
            groups.append([line])
        else:
            groups[-1].append(line)
    return [DraftParagraph(group, indented(group[0]), display) for group in groups]
