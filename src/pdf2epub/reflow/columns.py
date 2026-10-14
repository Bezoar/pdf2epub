"""Finding a page's text columns (RFL-R11) from an x-projection of its glyphs.

Every piece of text (a run of glyphs pdfminer set as one line) covers the stretches of the
page's width where its glyphs are. A **gutter** is a stretch, inside the text, at least a
little under an em wide, that almost no piece covers: only the few that cross it, such as
a centred running header, a page number or a title over both columns. The stretches
between gutters are columns; they count only when each holds enough lines, wide enough
for its column, side by side with the others. That leaves out tables (narrow cells),
verse and ragged text (whose gaps don't line up) and a lone label beside a block.
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass
from itertools import pairwise
from statistics import median

import numpy as np

# The projection's resolution, in points.
_STEP = 0.5
# A gutter is at least this many ems wide, and crossed by no more than this share of the
# page's pieces.
_GUTTER_EM, _CROSSING_SHARE = 0.8, 0.1
# Each column holds at least this many lines, is at least this many ems wide, its typical
# line fills at least this share of it, and its lines sit beside the next column's for
# at least this share of the shorter column's height.
_MIN_LINES, _MIN_WIDTH_EM, _FILL, _BESIDE = 5, 8.0, 0.5, 0.5


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
    left = min(piece.x0 for piece in pieces)
    bins = math.ceil((max(piece.x1 for piece in pieces) - left) / _STEP) + 1
    coverage = np.zeros(bins, dtype=np.int32)
    for piece in pieces:
        covered = np.zeros(bins, dtype=bool)
        for x0, x1 in piece.glyphs:
            covered[int((x0 - left) / _STEP) : math.ceil((x1 - left) / _STEP)] = True
        coverage += covered
    candidates = _gaps(coverage <= _CROSSING_SHARE * len(pieces), left, _GUTTER_EM * size)
    if not candidates:
        return []
    if _columns_hold(pieces, candidates, size):
        return candidates
    # Some gap isn't a gutter (say, one inside a table beside the text): try each alone.
    for gutter in candidates:
        if _columns_hold(pieces, [gutter], size):
            return [gutter]
    return []


def _gaps(empty: np.ndarray, left: float, min_width: float) -> list[Gutter]:
    """Runs of nearly empty bins at least ``min_width`` wide, not touching either edge."""
    gaps: list[Gutter] = []
    start: int | None = None
    for index, is_empty in enumerate(empty):
        if is_empty and start is None:
            start = index
        elif not is_empty and start is not None:
            if start > 0 and (index - start) * _STEP >= min_width:
                gaps.append(Gutter(left + start * _STEP, left + index * _STEP))
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
