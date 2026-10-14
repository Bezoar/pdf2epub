"""Headings in typeset text (RFL-R20): which blocks are headings, and their levels.

A block is a heading when it is larger or bolder than body text, at most about two lines
long, and set apart by vertical space from what is above or below it. Levels come from
the distinct heading styles (size, then weight), largest first, capped at 6.
"""

from pdf2epub.reflow.furniture import PageBlocks
from pdf2epub.reflow.layout import TextBlock, Typography, block_gap

# "At most about two lines": a title that wraps once more still counts.
_MAX_LINES = 3
# Heading sizes this close (points) are one style.
_SIZE_STEP = 0.5
_MAX_LEVEL = 6

Key = tuple[int, int]
"""(page, index of the block on that page)."""
_Style = tuple[float, bool]


def heading_levels(
    pages: list[PageBlocks], skip: set[Key], typography: Typography
) -> dict[Key, int]:
    """The level (1-6) of every heading block, leaving out the blocks in ``skip``
    (furniture)."""
    styles: dict[Key, _Style] = {}
    for page in pages:
        kept = [(i, b) for i, b in enumerate(page.blocks) if (page.page, i) not in skip]
        for n, (index, block) in enumerate(kept):
            above = kept[n - 1][1] if n > 0 else None
            below = kept[n + 1][1] if n + 1 < len(kept) else None
            if _is_heading(block, above, below, typography):
                styles[(page.page, index)] = _style(block)
    ranked = sorted(set(styles.values()), reverse=True)
    return {key: min(ranked.index(style) + 1, _MAX_LEVEL) for key, style in styles.items()}


def _style(block: TextBlock) -> _Style:
    return round(block.size / _SIZE_STEP) * _SIZE_STEP, block.bold


def _is_heading(
    block: TextBlock, above: TextBlock | None, below: TextBlock | None, typography: Typography
) -> bool:
    if len(block.lines) > _MAX_LINES:
        return False
    larger = typography.is_display(block.size)
    bolder = block.bold and block.size >= typography.body_size - _SIZE_STEP
    if not (larger or bolder):
        return False
    limit = block_gap(typography, typography.body_size)
    apart_above = above is None or block.top - above.bottom > limit
    apart_below = below is None or below.top - block.bottom > limit
    return apart_above or apart_below
