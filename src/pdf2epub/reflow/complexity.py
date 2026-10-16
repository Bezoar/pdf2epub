"""Page complexity (RFL-R13): whether a page has too much that reflow can't carry, so that
in ``mode = "auto"`` it becomes a page-image fallback with reason ``complex``.

The score is the largest of four measures, each divided by the level at which it alone
makes a page complex:

- the share of the page under images and filled shapes;
- table rules: a grid of crossing rules, or three or more horizontal rules of one width
  (a table ruled above, below and under its header);
- the share of mathematical glyphs;
- the share of lines that can't be classified as running text: pieces of rows broken
  into three or more parts by wide gaps, as in a table set without rules.

A page whose score reaches 1 is complex. The levels are internal constants, calibrated
on the fixtures and the public-domain sample. Shares are of the visible page (its
CropBox, RFL-R9): the sample's opening photograph and its caption cover 70% of it, and
reflow as a captioned image.
"""

from pdf2epub.reflow.extract import Line, PageText, Rule

_COVERED = 0.75
_MATH = 0.03
_UNCLASSIFIED = 0.3
# A grid has at least this many crossings of a horizontal and a vertical rule.
_GRID_CROSSINGS = 6
# Horizontal rules of one width, enough of them to rule a table.
_SAME_WIDTH_RULES = 3
# Rules this close, in points, touch; widths this close are the same.
_TOUCH = 1.5
# Lines overlapping vertically by more than this share of the shorter one share a row.
_SAME_ROW = 0.5
_MIN_PARTS = 3


def is_complex(page: PageText) -> bool:
    return score(page) >= 1.0


def score(page: PageText) -> float:
    graphics = page.graphics
    measures = [
        graphics.covered / _COVERED,
        2.0 if _table_rules(graphics.rules) else 0.0,
        (graphics.math / graphics.glyphs / _MATH) if graphics.glyphs else 0.0,
        _unclassified(page.lines) / _UNCLASSIFIED,
    ]
    return max(measures)


def _table_rules(rules: list[Rule]) -> bool:
    across = [rule for rule in rules if rule.horizontal]
    down = [rule for rule in rules if not rule.horizontal]
    crossings = sum(_cross(h, v) for h in across for v in down)
    if crossings >= _GRID_CROSSINGS:
        return True
    widths: list[list[Rule]] = []
    for rule in sorted(across, key=lambda r: (r.x0, r.x1)):
        group = next((g for g in widths if _same_width(g[0], rule)), None)
        if group is None:
            widths.append([rule])
        else:
            group.append(rule)
    return any(len(group) >= _SAME_WIDTH_RULES for group in widths)


def _cross(across: Rule, down: Rule) -> bool:
    return (
        across.x0 - _TOUCH <= down.x0 <= across.x1 + _TOUCH
        and down.top - _TOUCH <= across.top <= down.bottom + _TOUCH
    )


def _same_width(a: Rule, b: Rule) -> bool:
    return abs(a.x0 - b.x0) <= _TOUCH and abs(a.x1 - b.x1) <= _TOUCH


def _unclassified(lines: list[Line]) -> float:
    """The share of the page's lines that sit in rows of three or more parts."""
    if not lines:
        return 0.0
    rows: list[list[Line]] = []
    for line in sorted(lines, key=lambda line: line.top):
        if rows and _overlap(rows[-1][0], line) > _SAME_ROW:
            rows[-1].append(line)
        else:
            rows.append([line])
    scattered = sum(len(row) for row in rows if len(row) >= _MIN_PARTS)
    return scattered / len(lines)


def _overlap(a: Line, b: Line) -> float:
    shared = min(a.bottom, b.bottom) - max(a.top, b.top)
    shorter = min(a.bottom - a.top, b.bottom - b.top)
    return shared / shorter if shorter > 0 else 0.0
