"""Furniture removal (RFL-R16): running headers, running footers and page numbers.

The top and bottom bands of the pages are compared across the document. The candidates
on each page are the single-line blocks nearest its top and bottom edges, in body size or
smaller. Candidates are clustered by their distance from the edge; a cluster that appears
on enough pages is furniture when most of its blocks either repeat (with any number
masked) on several pages, or look like a page number. Every candidate in such a cluster
is removed, so a running header that changes with the chapter goes too.

Page numbers found this way are kept, by page, for page sequence gaps (RFL-R29).
"""

import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from pdf2epub.reflow.layout import TextBlock, Typography

# Share of the page height, from each edge, in which furniture can sit.
_BAND = 0.15
# At most this many candidates per edge of a page (e.g. a header and a page number).
_PER_EDGE = 2
# A cluster must appear on at least this many pages, and this share of the pages.
_MIN_PAGES, _MIN_SHARE = 3, 0.25
# Candidates within this distance (points) of each other's edge distance cluster together.
_CLUSTER_GAP = 3.0
# Text repeats when it appears on at least this many pages of its cluster.
_REPEATS = 2

_DIGITS = re.compile(r"\d+")
_PAGE_NUMBER = re.compile(
    r"^(?:page\s+|p\.\s*)?[\W_]*(\d{1,4}|[ivxlcdm]{1,8})[\W_]*$", re.IGNORECASE
)


@dataclass(frozen=True)
class PageBlocks:
    page: int
    height: float
    blocks: list[TextBlock]


@dataclass
class Furniture:
    removed: set[tuple[int, int]] = field(default_factory=set)
    """(page, index of the block on that page) of every furniture block."""
    page_numbers: dict[int, str] = field(default_factory=dict)
    """The printed page number found on each page that has one."""


@dataclass(frozen=True)
class _Candidate:
    page: int
    index: int
    edge: str
    distance: float
    text: str


def page_number(text: str) -> str | None:
    """The number in ``text`` if it is a page number (``12``, ``xiv``, ``— 12 —``)."""
    match = _PAGE_NUMBER.match(text.strip())
    return match.group(1) if match else None


def find_furniture(pages: list[PageBlocks], typography: Typography) -> Furniture:
    furniture = Furniture()
    candidates = [c for page in pages for c in _candidates(page, typography)]
    needed = max(_MIN_PAGES, math.ceil(_MIN_SHARE * len(pages)))
    for cluster in _clusters(candidates):
        if len({c.page for c in cluster}) < needed or not _is_furniture(cluster):
            continue
        for c in cluster:
            furniture.removed.add((c.page, c.index))
            number = page_number(c.text)
            if number is not None:
                furniture.page_numbers[c.page] = number
    return furniture


def _candidates(page: PageBlocks, typography: Typography) -> list[_Candidate]:
    found: dict[int, _Candidate] = {}
    indexed = list(enumerate(page.blocks))
    for edge, order in (("top", indexed), ("bottom", indexed[::-1])):
        for index, block in order[:_PER_EDGE]:
            distance = block.top if edge == "top" else page.height - block.bottom
            if (
                len(block.lines) != 1
                or distance > _BAND * page.height
                or typography.is_display(block.size)
            ):
                break
            found.setdefault(index, _Candidate(page.page, index, edge, distance, block.text))
    return list(found.values())


def _clusters(candidates: list[_Candidate]) -> list[list[_Candidate]]:
    clusters: list[list[_Candidate]] = []
    for edge in ("top", "bottom"):
        on_edge = sorted((c for c in candidates if c.edge == edge), key=lambda c: c.distance)
        for c in on_edge:
            if (
                clusters
                and clusters[-1][0].edge == edge
                and (c.distance - clusters[-1][-1].distance <= _CLUSTER_GAP)
            ):
                clusters[-1].append(c)
            else:
                clusters.append([c])
    return clusters


def _is_furniture(cluster: list[_Candidate]) -> bool:
    pages_by_text: defaultdict[str, set[int]] = defaultdict(set)
    for c in cluster:
        pages_by_text[_DIGITS.sub("#", c.text.casefold())].add(c.page)
    repeats: Counter[bool] = Counter(
        len(pages_by_text[_DIGITS.sub("#", c.text.casefold())]) >= _REPEATS
        or page_number(c.text) is not None
        for c in cluster
    )
    return repeats[True] * 2 > len(cluster)
