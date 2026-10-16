"""Finding a page's text columns (RFL-R11) from an x-projection of its glyphs.

Every piece of text (a run of glyphs pdfminer set as one line) covers the stretches of the
page's width where its glyphs are. A **gutter** is a stretch, inside the text, at least a
little under an em wide, that almost no piece covers: only the few that cross it, such as
a centred running header, a page number or a title over both columns. The stretches
between gutters are columns; they count only when each holds enough lines, wide enough
for its column, side by side with the others. That leaves out tables (narrow cells),
verse and ragged text (whose gaps don't line up) and a lone label beside a block.

A block across the columns, such as a title block over them or a figure under them, can
cross the gutter with more lines than that allows. Its lines stand alone on their rows,
while each column's lines have the next column's beside them, so the page is looked at
again in bands between such blocks: a band's columns count when they are alike, of one
width and one type size, as columns of running text are (a code listing with its comments
beside it is not).
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass
from itertools import pairwise
from statistics import median

import numpy as np
from numpy.typing import NDArray

# The projection's resolution, in points, made coarser when the text spans so wide
# a stretch (a hostile page can be enormous) that it would need more bins than this.
_STEP, _MAX_BINS = 0.5, 20_000
# A gutter is at least this many ems wide, and crossed by no more than this share of the
# page's pieces.
_GUTTER_EM, _CROSSING_SHARE = 0.8, 0.1
# Each column holds at least this many lines, is at least this many ems wide, its typical
# line fills at least this share of it, and its lines sit beside the next column's for
# at least this share of the shorter column's height.
_MIN_LINES, _MIN_WIDTH_EM, _FILL, _BESIDE = 5, 8.0, 0.5, 0.5
# When lines across the columns cross a gutter too often, the gutter is looked for again
# in bands of the page holding at least this share of its pieces, for columns alike:
# their widths within this share of each other and their type the same size. A piece is
# compared with at most this many below it for a piece beside it.
_BAND_SHARE, _EQUAL, _NEIGHBOURS = 0.25, 0.75, 64


@dataclass(frozen=True)
class Piece:
    """A run of glyphs on one line: where each glyph is across the page, and the line's
    vertical extent and font size."""

    glyphs: Sequence[tuple[float, float]]
    """Each glyph's left and right edge."""
    top: float
    bottom: float
    size: float

    @property
    def x0(self) -> float:
        return min(x0 for x0, _ in self.glyphs)

    @property
    def x1(self) -> float:
        return max(x1 for _, x1 in self.glyphs)


@dataclass(frozen=True)
class Gutter:
    x0: float
    x1: float

    @property
    def middle(self) -> float:
        return (self.x0 + self.x1) / 2

    def crossed_by(self, piece: Piece) -> bool:
        """A glyph of ``piece`` sits in the middle half of the gutter, as in a heading or
        a page number centred across the columns. A line of a column may reach into the
        gutter's edges (the gutter is where almost nothing is, not where nothing is)."""
        quarter = (self.x1 - self.x0) / 4
        return any(
            x0 < self.middle + quarter and x1 > self.middle - quarter for x0, x1 in piece.glyphs
        )


def find_gutters(pieces: Sequence[Piece]) -> list[Gutter]:
    """The gutters between the page's text columns, left to right; none for a page set in
    one column."""
    pieces = [piece for piece in pieces if piece.glyphs]
    if len(pieces) < 2 * _MIN_LINES:
        return []
    size = median(piece.size for piece in pieces)
    gutters = _gutters_among(pieces, size)
    if gutters:
        return gutters
    # A block across the columns (a title over them, a figure under or between them) can
    # cross the gutter with more lines than a page allows. Look again in each band of the
    # page between such blocks, largest first, for columns alike.
    for band in sorted(_bands(pieces), key=len, reverse=True):
        if len(band) < max(2 * _MIN_LINES, _BAND_SHARE * len(pieces)):
            break
        gutters = _gutters_among(band, size)
        if gutters and _alike(band, gutters):
            return gutters
    return []


def _gutters_among(pieces: Sequence[Piece], size: float) -> list[Gutter]:
    """The gutters in the x-projection of ``pieces`` that their columns bear out."""
    left = min(piece.x0 for piece in pieces)
    span = max(piece.x1 for piece in pieces) - left
    step = max(_STEP, span / _MAX_BINS)
    bins = math.ceil(span / step) + 1
    coverage = np.zeros(bins, dtype=np.int32)
    for piece in pieces:
        covered = np.zeros(bins, dtype=bool)
        for x0, x1 in piece.glyphs:
            covered[int((x0 - left) / step) : math.ceil((x1 - left) / step)] = True
        coverage += covered
    candidates = _gaps(coverage, _CROSSING_SHARE * len(pieces), left, step, _GUTTER_EM * size)
    if not candidates:
        return []
    if _columns_hold(pieces, candidates, size):
        return candidates
    # Some gap isn't a gutter (say, one inside a table beside the text): try each alone.
    for gutter in candidates:
        if _columns_hold(pieces, [gutter], size):
            return [gutter]
    return []


def _bands(pieces: Sequence[Piece]) -> list[list[Piece]]:
    """The page's pieces, top to bottom, cut into bands wherever two or more pieces in a
    row stand alone: with no piece beside them on the same line, as the lines of a title
    or a figure across the columns do. A column's line has the next column's beside it."""
    ordered = sorted(pieces, key=lambda piece: piece.top)
    beside = [False] * len(ordered)
    for index, piece in enumerate(ordered):
        for offset, other in enumerate(ordered[index + 1 : index + 1 + _NEIGHBOURS], 1):
            if other.top >= piece.bottom:
                break
            shorter = min(piece.bottom - piece.top, other.bottom - other.top)
            overlap = min(piece.bottom, other.bottom) - other.top
            if overlap >= shorter / 2 and (other.x0 >= piece.x1 or other.x1 <= piece.x0):
                beside[index] = beside[index + offset] = True
    bands: list[list[Piece]] = [[]]
    alone: list[Piece] = []
    for piece, is_beside in zip(ordered, beside, strict=True):
        if not is_beside:
            alone.append(piece)
            continue
        if len(alone) >= 2:
            bands.append([])
        else:
            bands[-1].extend(alone)
        alone = []
        bands[-1].append(piece)
    if len(alone) >= 2:
        bands.append(alone)
    else:
        bands[-1].extend(alone)
    return bands


def _alike(pieces: Sequence[Piece], gutters: list[Gutter]) -> bool:
    """The columns' lines span widths within ``_EQUAL`` of each other and are set in type
    of one size, as columns of running text are; a code listing with comments beside it,
    or a caption beside a narrowed paragraph, is not."""
    columns = [column_lines(pieces, gutters, index) for index in range(len(gutters) + 1)]
    widths = [max(p.x1 for p in lines) - min(p.x0 for p in lines) for lines in columns]
    sizes = {median(p.size for p in lines) for lines in columns}
    return min(widths) >= _EQUAL * max(widths) and len(sizes) == 1


def _gaps(
    coverage: NDArray[np.int32], limit: float, left: float, step: float, min_width: float
) -> list[Gutter]:
    """Runs of bins covered by no more than ``limit`` pieces, at least ``min_width`` wide,
    not touching either edge. Each is narrowed to the stretch between its first and last
    least-covered bin, if that is still wide enough: the longest lines of a ragged column
    reach a little way into the gap, and would otherwise seem to cross its middle."""
    gaps: list[Gutter] = []
    start: int | None = None
    for index, covered in enumerate(coverage):
        if covered <= limit and start is None:
            start = index
        elif covered > limit and start is not None:
            if start > 0 and (index - start) * step >= min_width:
                run = coverage[start:index]
                least = np.flatnonzero(run == run.min())
                first, last = start + int(least[0]), start + int(least[-1]) + 1
                if (last - first) * step < min_width:
                    first, last = start, index
                gaps.append(Gutter(left + first * step, left + last * step))
            start = None
    return gaps


def _columns_hold(pieces: Sequence[Piece], gutters: list[Gutter], size: float) -> bool:
    edges = [
        min(piece.x0 for piece in pieces),
        *(g.middle for g in gutters),
        max(piece.x1 for piece in pieces),
    ]
    columns = [column_lines(pieces, gutters, index) for index in range(len(gutters) + 1)]
    for (start, end), lines in zip(pairwise(edges), columns, strict=True):
        width = end - start
        if len(lines) < _MIN_LINES or width < _MIN_WIDTH_EM * size:
            return False
        if median(x1 - x0 for x0, x1 in lines_extent(lines)) < _FILL * width:
            return False
    for this, that in pairwise(columns):
        top = max(min(p.top for p in this), min(p.top for p in that))
        bottom = min(max(p.bottom for p in this), max(p.bottom for p in that))
        shorter = min(_height(this), _height(that))
        if bottom - top < _BESIDE * shorter:
            return False
    return True


def column_of(piece: Piece, gutters: Sequence[Gutter]) -> int | None:
    """The index of the column ``piece`` belongs in, or None when it crosses a gutter
    (a heading or a page number across the columns). A piece with glyphs in two columns
    that doesn't cross the gutter between them is two pieces: ``split`` it first."""
    if any(g.crossed_by(piece) for g in gutters):
        return None
    middle = (piece.x0 + piece.x1) / 2
    return sum(middle > g.middle for g in gutters)


def split(piece: Piece, gutters: Sequence[Gutter]) -> list[list[int]]:
    """The indexes of ``piece``'s glyphs, grouped by column, left to right; one group if
    the piece crosses a gutter."""
    everything = list(range(len(piece.glyphs)))
    if any(gutter.crossed_by(piece) for gutter in gutters):
        return [everything]
    groups: dict[int, list[int]] = {}
    for index, (x0, x1) in enumerate(piece.glyphs):
        groups.setdefault(sum((x0 + x1) / 2 > g.middle for g in gutters), []).append(index)
    return [groups[key] for key in sorted(groups)]


def column_lines(pieces: Sequence[Piece], gutters: list[Gutter], index: int) -> list[Piece]:
    """The parts of ``pieces`` that fall in column ``index``."""
    found: list[Piece] = []
    for piece in pieces:
        for group in split(piece, gutters):
            part = Piece([piece.glyphs[i] for i in group], piece.top, piece.bottom, piece.size)
            if column_of(part, gutters) == index:
                found.append(part)
    return found


def lines_extent(lines: Sequence[Piece]) -> list[tuple[float, float]]:
    return [(line.x0, line.x1) for line in lines]


def _height(lines: Sequence[Piece]) -> float:
    return max(p.bottom for p in lines) - min(p.top for p in lines)
