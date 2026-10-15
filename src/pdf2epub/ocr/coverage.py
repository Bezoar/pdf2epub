"""Coverage (OCR-R16): how much of a page's printed text a set of boxes holds.

One rule scores both an OCR attempt (its word boxes, in the cleaned page image) and an
existing text layer (its character boxes, in the page rendered for the text-layer check,
OCR-R7). It counts **text-like ink** only, so that what is not text (scanner and film
borders, picture plates, stamps, ornaments) neither counts against the boxes nor is needed
to pass:

1. Ink is the dark pixels after Otsu binarisation. A page more than half ink is light
   print on a dark ground, and is inverted first. Ink connected to the image's edge (a
   border) is set aside and Otsu runs again on the rest, so a black border doesn't set the
   threshold that faint print must pass.
2. The scale is the **box height**: the median height of the boxes. A **unit** of ink is
   the area of a square one box height across.
3. A connected ink component is text-like when it doesn't touch the image's edge, is at
   most ``TEXT_HEIGHT`` box heights tall and ``TEXT_WIDTH`` wide, is larger than a speck,
   and its centre is not in a **picture region**: the box (widened by one box height on
   each side) of a larger component at least ``PICTURE_FILL`` ink.
4. A text-like component is covered when any of its pixels is inside a box: boxes that sit
   a little off their glyphs (as Internet Archive layers' do, set at the descenders) still
   cover them. The **share** is the covered text-like ink over all of it.
5. **Coverage** is the share, unless the boxes hold some of the text-like ink and less than
   ``MAX_UNCOVERED`` units of it lie outside every box: then the boxes miss too little text
   to matter (pages of front matter, plates with captions, test charts), and coverage is
   1. Boxes that hold none of it (no words, or words read off the text) get the share, 0.
"""

from collections.abc import Iterable
from dataclasses import dataclass

import cv2
import numpy as np
from numpy.typing import NDArray
from PIL import Image

Box = tuple[float, float, float, float]
"""(left, top, right, bottom) in pixels from the image's top-left corner."""

# --- The constants (OCR-R8, OCR-R16) ----------------------------------------------------
# Calibrated on the must-trust and must-reject fixtures and on the Internet Archive scans
# S7 and S9 (``scripts/calibrate_text_layer.py``; issue #90).

MAX_UNCOVERED = 80.0
"""Units of text-like ink that may lie outside every box before coverage is the share:
about 13 lines of S7's body text, 15 of S9's."""
TEXT_HEIGHT = 3.0
"""A text-like component is at most this many box heights tall..."""
TEXT_WIDTH = 25.0
"""...and at most this many box heights wide."""
SPECK = 0.1
"""A component smaller than a square this share of a box height across is a speck (never
smaller than ``MIN_SPECK`` pixels)."""
MIN_SPECK = 3
PICTURE_FILL = 0.2
"""A component too large to be text is a picture when at least this share of its box is
ink (a thin ring or frame is not)."""


@dataclass(frozen=True)
class Coverage:
    """How much of a page's text-like ink the boxes hold."""

    share: float
    """Covered text-like ink over all text-like ink; 1 with none."""
    uncovered: float
    """Text-like ink outside every box, in units."""

    @property
    def value(self) -> float:
        """The coverage: the share, or 1 when the boxes hold some text-like ink and less
        than ``MAX_UNCOVERED`` units are uncovered."""
        return 1.0 if self.share > 0 and self.uncovered < MAX_UNCOVERED else self.share


def measure(image: Image.Image, boxes: Iterable[Box]) -> Coverage:
    """The coverage of ``image``'s text-like ink by ``boxes``."""
    grey = np.asarray(image.convert("L"), dtype=np.uint8)
    boxes = list(boxes)
    if grey.size == 0:
        return Coverage(1.0, 0.0)
    ink = _otsu(grey)
    if 2 * int(ink.sum()) > ink.size:  # light print on a dark ground
        grey = 255 - grey
        ink = _otsu(grey)
    labels, stats = _components(ink)
    heights = [bottom - top for _, top, _, bottom in boxes if bottom > top]
    scale = float(np.median(heights)) if heights else _text_height(stats, grey.shape)
    border = _edge(stats, grey.shape)[labels]
    if border.any():
        reach = max(round(scale / 6), 1)
        border = cv2.dilate(border.astype(np.uint8), _square(reach)) > 0
        rest = grey[~border]
        if rest.size and rest.min() < rest.max():
            limit, _ = cv2.threshold(rest.reshape(1, -1), 0, 255, cv2.THRESH_OTSU)
            ink = (grey <= limit) & ~border
        else:
            ink = np.zeros_like(ink)
    labels, stats = _components(ink)
    text = _text_like(stats, grey.shape, scale)
    covered = np.zeros(len(stats), dtype=bool)
    covered[np.unique(labels[ink & _inside(grey.shape, boxes)])] = True
    area = stats[:, cv2.CC_STAT_AREA]
    total = int(area[text].sum())
    missed = int(area[text & ~covered].sum())
    if total == 0:
        return Coverage(1.0, 0.0)
    return Coverage((total - missed) / total, missed / scale**2)


def _components(ink: NDArray[np.bool_]) -> tuple[NDArray[np.int32], NDArray[np.int32]]:
    """Each pixel's component label, and each component's stats (label 0: background)."""
    _, labels, stats, _ = cv2.connectedComponentsWithStats(ink.astype(np.uint8), connectivity=8)
    return np.asarray(labels, dtype=np.int32), np.asarray(stats, dtype=np.int32)


def _otsu(grey: NDArray[np.uint8]) -> NDArray[np.bool_]:
    _, binary = cv2.threshold(grey, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return np.asarray(binary == 0)


def _square(reach: int) -> NDArray[np.uint8]:
    return np.ones((2 * reach + 1, 2 * reach + 1), dtype=np.uint8)


def _edge(stats: NDArray[np.int32], shape: tuple[int, ...]) -> NDArray[np.bool_]:
    """Which components touch the image's edge (never the background, label 0)."""
    rows, columns = shape[0], shape[1]
    x, y = stats[:, cv2.CC_STAT_LEFT], stats[:, cv2.CC_STAT_TOP]
    w, h = stats[:, cv2.CC_STAT_WIDTH], stats[:, cv2.CC_STAT_HEIGHT]
    edge = (x == 0) | (y == 0) | (x + w >= columns) | (y + h >= rows)
    edge[0] = False
    return np.asarray(edge)


def _text_height(stats: NDArray[np.int32], shape: tuple[int, ...]) -> float:
    """With no boxes to measure, the median height of the components off the edge."""
    inner = ~_edge(stats, shape)
    inner[0] = False
    heights = stats[inner, cv2.CC_STAT_HEIGHT]
    return float(np.median(heights)) if heights.size else 1.0


def _text_like(stats: NDArray[np.int32], shape: tuple[int, ...], scale: float) -> NDArray[np.bool_]:
    rows, columns = shape[0], shape[1]
    x, y = stats[:, cv2.CC_STAT_LEFT], stats[:, cv2.CC_STAT_TOP]
    w, h = stats[:, cv2.CC_STAT_WIDTH], stats[:, cv2.CC_STAT_HEIGHT]
    area = stats[:, cv2.CC_STAT_AREA]
    edge = _edge(stats, shape)
    large = (h > TEXT_HEIGHT * scale) | (w > TEXT_WIDTH * scale)
    speck = area < max(MIN_SPECK, (SPECK * scale) ** 2)
    pictures = np.zeros((rows, columns), dtype=bool)
    reach = max(round(scale), 1)
    for label in np.flatnonzero(large & ~edge):
        if label and area[label] >= PICTURE_FILL * w[label] * h[label]:
            top, left = max(y[label] - reach, 0), max(x[label] - reach, 0)
            pictures[top : y[label] + h[label] + reach, left : x[label] + w[label] + reach] = True
    in_picture = pictures[np.clip(y + h // 2, 0, rows - 1), np.clip(x + w // 2, 0, columns - 1)]
    text = ~(edge | large | speck | in_picture)
    text[0] = False
    return np.asarray(text)


def _inside(shape: tuple[int, ...], boxes: list[Box]) -> NDArray[np.bool_]:
    inside = np.zeros(shape[:2], dtype=bool)
    rows, columns = shape[0], shape[1]
    for left, top, right, bottom in boxes:
        y0, y1 = max(int(top), 0), min(int(np.ceil(bottom)), rows)
        x0, x1 = max(int(left), 0), min(int(np.ceil(right)), columns)
        if y1 > y0 and x1 > x0:  # a box off the image covers nothing (no wrap-around)
            inside[y0:y1, x0:x1] = True
    return inside
