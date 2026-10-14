"""Chapters and the table of contents (RFL-R23, RFL-R24).

Chapters come from the PDF outline when at least 3 of its entries resolve to pages: each
top-level entry starts a chapter at the first block at or after its destination, and
nested entries become nested TOC entries. Otherwise every level-1 heading starts a
chapter, and so does any heading that matches a chapter pattern (``Chapter 7``, ``Part
II``, ``Prologue``); lower headings become nested TOC entries. Content before the first
chapter is a front-matter chapter with no TOC entry. A book with no chapter start at all
is one chapter, titled with the book title.
"""

import re
from bisect import bisect_left
from dataclasses import dataclass, field
from itertools import accumulate, pairwise

from pdf2epub.reflow.model import Block, Chapter, Heading, PageBreak, Text, TocEntry
from pdf2epub.reflow.source import OutlineEntry

Position = tuple[int, float]
"""Where a block starts: (1-based page, distance from the top of the page)."""

# Chapters come from the outline when at least this many entries resolve to pages.
_MIN_OUTLINE = 3

_ONES = ["one", "two", "three", "four", "five", "six", "seven", "eight", "nine"]
_TEENS = ["ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen"]
_TEENS += ["seventeen", "eighteen", "nineteen"]
_TENS = ["twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]
_NUMBER_WORDS = sorted(
    [
        *_ONES,
        *_TEENS,
        *_TENS,
        *(f"{tens}[- ]?{one}" for tens in _TENS for one in _ONES),
        "(?:one )?hundred",
    ],
    key=len,
    reverse=True,
)
_CHAPTER = re.compile(
    rf"^(?:(?:chapter|part)\s+(?:\d+|[ivxlcdm]+|{'|'.join(_NUMBER_WORDS)})|prologue|epilogue)\b",
    re.IGNORECASE,
)


def is_chapter_heading(text: str) -> bool:
    """``text`` matches a chapter pattern (RFL-R24)."""
    return _CHAPTER.match(text.strip()) is not None


def make_chapters(
    blocks: list[Block], positions: list[Position], outline: list[OutlineEntry], title: str
) -> tuple[list[Chapter], list[TocEntry]]:
    """Split the book's blocks (with where each starts) into chapters, and build the TOC.
    ``title`` is the book title, for a book with no chapters."""
    resolved = [entry for entry in outline if entry.page is not None]
    if len(resolved) >= _MIN_OUTLINE:
        found = _from_outline(blocks, positions, outline)
    else:
        found = _from_headings(blocks)
    if found is None:
        return [Chapter(title, blocks)], [TocEntry(title, chapter=0)]
    return found


@dataclass
class _Node:
    label: str
    target: int
    """Index of the block it points to."""
    starts: bool
    """It starts a chapter."""
    anchor: str | None = None
    """Where it links inside its chapter, unless it starts one."""
    children: list["_Node"] = field(default_factory=list)


def _from_outline(
    blocks: list[Block], positions: list[Position], outline: list[OutlineEntry]
) -> tuple[list[Chapter], list[TocEntry]] | None:
    roots: list[_Node] = []
    stack: list[tuple[int, _Node | None]] = []
    """The entries the next one may nest in; None for one that resolves to no block."""
    # The furthest position reached so far, at each block: sorted, so the first block at
    # or after a destination is found by bisection.
    reached = list(accumulate(positions, max))
    for entry in outline:
        while stack and stack[-1][0] >= entry.level:
            stack.pop()
        target = len(blocks)
        if entry.page is not None:
            top = -1.0 if entry.top is None else entry.top
            target = bisect_left(reached, (entry.page, top))
        if target == len(blocks):
            # It points nowhere, or past the last block: no TOC entry, but it keeps its
            # place in the tree, so its children are not promoted to chapters.
            stack.append((entry.level, None))
            continue
        parent = next((node for _, node in reversed(stack) if node is not None), None)
        block = blocks[target]
        if isinstance(block, Heading) and positions[target][0] == entry.page:
            anchor = block.anchor
        else:
            # Not at a heading on its page: link to the start of that page, whose
            # page-break marker has this ID (EPUB-R19).
            anchor = f"page-{entry.page}"
        node = _Node(entry.title or f"Page {entry.page}", target, not stack, anchor)
        # Under an entry that resolves nowhere, with no resolved ancestor, it is a
        # top-level TOC entry that doesn't start a chapter.
        (parent.children if parent is not None else roots).append(node)
        stack.append((entry.level, node))
    if not any(node.starts for node in roots):
        return None
    return _assemble(blocks, roots)


def _from_headings(blocks: list[Block]) -> tuple[list[Chapter], list[TocEntry]] | None:
    roots: list[_Node] = []
    stack: list[tuple[int, _Node]] = []
    for index, block in enumerate(blocks):
        if not isinstance(block, Heading):
            continue
        label = heading_text(block)
        if block.level == 1 or is_chapter_heading(label):
            node = _Node(label, index, starts=True)
            roots.append(node)
            stack = [(0, node)]
            continue
        if not stack:
            continue  # a heading in the front matter: no TOC entry
        while stack[-1][0] >= block.level:
            stack.pop()
        node = _Node(label, index, starts=False, anchor=block.anchor)
        stack[-1][1].children.append(node)
        stack.append((block.level, node))
    if not roots:
        return None
    return _assemble(blocks, roots)


def heading_text(heading: Heading) -> str:
    return " ".join("".join(i.text for i in heading.inlines if isinstance(i, Text)).split())


def _assemble(blocks: list[Block], roots: list[_Node]) -> tuple[list[Chapter], list[TocEntry]]:
    starts = sorted({_pull_back(blocks, node.target) for node in roots if node.starts})
    if starts[0] > 0:
        starts.insert(0, 0)  # front matter
    bounds = [*starts, len(blocks)]
    titles: dict[int, str] = {}
    for node in roots:
        if node.starts:
            titles.setdefault(_pull_back(blocks, node.target), node.label)
    chapters = [Chapter(titles.get(start), blocks[start:end]) for start, end in pairwise(bounds)]

    def chapter_of(target: int) -> int:
        return bisect_left(starts, target + 1) - 1

    def entry(node: _Node) -> TocEntry:
        chapter = chapter_of(node.target)
        anchor = None if node.starts else node.anchor
        return TocEntry(node.label, chapter, anchor, [entry(child) for child in node.children])

    return chapters, [entry(node) for node in roots]


def _pull_back(blocks: list[Block], start: int) -> int:
    """A chapter starting at ``start`` also takes the page-break markers right before it,
    so a chapter that opens a page starts with that page's marker."""
    while start > 0 and isinstance(blocks[start - 1], PageBreak):
        start -= 1
    return start
