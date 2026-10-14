"""Headings (RFL-R20, RFL-R21): which blocks are headings, and their levels.

A block is a heading when it is larger or bolder than body text, at most about two lines
long, and set apart by vertical space from what is above or below it. Levels come from
the distinct heading styles (size, then weight), largest first, capped at 6.

On an OCR'd page, where line height stands in for size and nothing is bold, a heading
must also be centred on the page or the first block at its top (RFL-R21).
"""

from collections.abc import Mapping

from pdf2epub.reflow.furniture import PageBlocks
from pdf2epub.reflow.layout import TextBlock, Typography, block_gap

# "At most about two lines": a title that wraps once more still counts.
_MAX_LINES = 3
# Heading sizes this close (points) are one style.
_SIZE_STEP = 0.5
_MAX_LEVEL = 6
# An OCR'd block is centred when its middle is within this many body sizes of the page's.
_CENTRED_EM = 1.5
# An OCR'd block is at the top of its page when it is the first block (furniture aside)
# and starts within this share of the page's height from its top edge.
_TOP_SHARE = 0.25

Key = tuple[int, int]
"""(page, index of the block on that page)."""
_Style = tuple[float, bool]


def heading_levels(
    pages: list[PageBlocks],
    skip: set[Key],
    typography: Typography,
    ocr_widths: Mapping[int, float] | None = None,
) -> dict[Key, int]:
    """The level (1-6) of every heading block, leaving out the blocks in ``skip``
    (furniture). ``ocr_widths`` gives the width of each OCR'd page, by page number."""
    ocr_widths = ocr_widths or {}
    styles: dict[Key, _Style] = {}
    for page in pages:
        kept = [(i, b) for i, b in enumerate(page.blocks) if (page.page, i) not in skip]
        for n, (index, block) in enumerate(kept):
            above = kept[n - 1][1] if n > 0 else None
            below = kept[n + 1][1] if n + 1 < len(kept) else None
            width = ocr_widths.get(page.page)
            at_top = n == 0 and block.top <= _TOP_SHARE * page.height
            if width is not None and not (at_top or _centred(block, width, typography)):
                continue
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


def _centred(block: TextBlock, width: float, typography: Typography) -> bool:
    x0 = min(line.x0 for line in block.lines)
    x1 = max(line.x1 for line in block.lines)
    return abs((x0 + x1) / 2 - width / 2) <= _CENTRED_EM * typography.body_size
