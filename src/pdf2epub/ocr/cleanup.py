"""Image cleanup before OCR (OCR-R18), with OpenCV.

A page render is cleaned in this order: orientation correction (by the angle the engine's
orientation detection gives, when it has one), deskew, border crop, rescale to
``OCR_DPI``, binarisation, denoise. ``prepare`` does the first four once per page; each
ladder step then binarises (Otsu or Sauvola) and, in its last step, denoises
(``variant_image``). The un-cleaned render is never changed: a page that falls back is
embedded from its own render.

Every step keeps the image's scale and size: the border crop clears what lies outside the
page's content to white rather than cutting it off. A word box in the cleaned image is
therefore in pixels of the uprighted page (``Frame``).
"""

from dataclasses import dataclass
from typing import Literal

import cv2
import numpy as np
from numpy.typing import NDArray
from PIL import Image

Binarisation = Literal["otsu", "sauvola"]

MAX_SKEW = 5.0
"""Degrees: a page tilted further than this is not a skewed scan; it is left alone."""
CROP_PADDING = 30
"""Pixels of white kept around the page's content after the border crop."""
SAUVOLA_WINDOW = 31
"""Pixels: about 2.5 mm at 300 DPI, a few text strokes wide."""
SAUVOLA_K, SAUVOLA_R = 0.2, 128.0
SPECK = 6
"""Ink (or paper) specks of at most this many pixels are noise, not text: at 300 DPI the
full stop of 8 pt type is several times larger."""
_SKEW_SCALE = 0.5
"""Skew is measured on the page at this scale, which is plenty for a tenth of a degree."""
_BORDER = 0.25
"""Dark regions touching the image's edge and spanning more than this share of its width
or height are scanner borders, not content."""

Grey = NDArray[np.uint8]


@dataclass(frozen=True)
class Frame:
    """How the cleaned image relates to the page render."""

    rotation: int
    """Clockwise degrees the render was turned to be upright: 0, 90, 180 or 270."""
    skew: float
    """Degrees the page was turned by deskew (counter-clockwise positive)."""


@dataclass(frozen=True)
class Prepared:
    """A page render uprighted, deskewed and cropped, at ``OCR_DPI``."""

    grey: Grey
    frame: Frame


def prepare(image: Image.Image, rotation: int = 0) -> Prepared:
    """``image`` (rendered at ``OCR_DPI``) turned ``rotation`` degrees clockwise, deskewed
    and cropped to its content. The page is rendered at ``OCR_DPI``, which is the rescale
    (OCR-R18): every later step keeps that scale."""
    grey: Grey = np.asarray(image.convert("L"), dtype=np.uint8)
    turns = {0: None, 90: cv2.ROTATE_90_CLOCKWISE, 180: cv2.ROTATE_180}
    turns[270] = cv2.ROTATE_90_COUNTERCLOCKWISE
    code = turns[rotation % 360]
    if code is not None:
        grey = np.asarray(cv2.rotate(grey, code), dtype=np.uint8)
    angle = skew_angle(grey)
    if angle:
        grey = _rotate(grey, angle)
    return Prepared(_crop(grey), Frame(rotation % 360, angle))


def skew_angle(grey: Grey) -> float:
    """The angle (degrees, counter-clockwise positive) that turns the page's text lines
    level: the angle whose row projection of the ink is the most sharply peaked. 0 when
    the page has no measurable lines or is tilted beyond ``MAX_SKEW``."""
    small = np.asarray(
        cv2.resize(grey, None, fx=_SKEW_SCALE, fy=_SKEW_SCALE, interpolation=cv2.INTER_AREA),
        dtype=np.uint8,
    )
    ys, xs = np.nonzero(_otsu(small) == 0)
    if len(ys) < 100:
        return 0.0
    ys = ys.astype(np.float64) - small.shape[0] / 2
    xs = xs.astype(np.float64) - small.shape[1] / 2

    def score(angle: float) -> float:
        radians = np.radians(angle)
        rows = np.round(ys * np.cos(radians) + xs * np.sin(radians)).astype(np.int64)
        counts = np.bincount(rows - rows.min())
        return float(np.square(counts.astype(np.float64)).sum())

    coarse = np.arange(-MAX_SKEW, MAX_SKEW + 0.001, 0.25)
    best = max(coarse, key=score)
    fine = np.arange(best - 0.25, best + 0.251, 0.05)
    angle = float(max(fine, key=score))
    if abs(angle) < 0.1 or abs(angle) >= MAX_SKEW:
        return 0.0
    # The projection is level when the page is turned back by the angle found.
    return -round(angle, 2)


def binarise(grey: Grey, method: Binarisation) -> Grey:
    """``grey`` as black (0) ink on white (255) paper, by Otsu's global threshold or
    Sauvola's local one."""
    if method == "otsu":
        return _otsu(grey)
    values = grey.astype(np.float64)
    size = (SAUVOLA_WINDOW, SAUVOLA_WINDOW)
    mean = cv2.boxFilter(values, -1, size, borderType=cv2.BORDER_REPLICATE)
    square = cv2.boxFilter(values * values, -1, size, borderType=cv2.BORDER_REPLICATE)
    deviation = np.sqrt(np.maximum(square - mean * mean, 0))
    threshold = mean * (1 + SAUVOLA_K * (deviation / SAUVOLA_R - 1))
    return np.where(values > threshold, 255, 0).astype(np.uint8)


def denoise(binary: Grey) -> Grey:
    """``binary`` without specks: ink specks of at most ``SPECK`` pixels become paper, and
    paper specks that small inside the ink become ink."""
    cleaned = binary.copy()
    for value, mask in ((255, binary == 0), (0, binary == 255)):
        count, labels, stats, _ = _components(mask)
        small = np.flatnonzero(stats[:, cv2.CC_STAT_AREA] <= SPECK)
        small = small[small != 0]  # label 0 is everything else
        if count > 1 and len(small):
            cleaned[np.isin(labels, small)] = value
    return cleaned


def variant_image(prepared: Prepared, method: Binarisation, clean: bool) -> Image.Image:
    """The image an attempt sends to the engine: the prepared page binarised by
    ``method``, and denoised if ``clean``."""
    binary = binarise(prepared.grey, method)
    return Image.fromarray(denoise(binary) if clean else binary)


def _components(
    mask: NDArray[np.bool_] | Grey,
) -> tuple[int, NDArray[np.int32], NDArray[np.int32], NDArray[np.float64]]:
    """The 8-connected components of ``mask``'s non-zero pixels: their count (with the
    background as label 0), the label of each pixel, and each label's stats."""
    image: NDArray[np.uint8] = np.asarray(mask, dtype=np.uint8)
    count, labels, stats, centroids = cv2.connectedComponentsWithStats(image, connectivity=8)
    return (
        int(count),
        np.asarray(labels, dtype=np.int32),
        np.asarray(stats, dtype=np.int32),
        np.asarray(centroids, dtype=np.float64),
    )


def _otsu(grey: Grey) -> Grey:
    _, binary = cv2.threshold(grey, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return binary.astype(np.uint8)


def _rotate(grey: Grey, angle: float) -> Grey:
    """``grey`` turned ``angle`` degrees counter-clockwise about its centre, same size,
    with white filling the corners."""
    height, width = grey.shape
    matrix = cv2.getRotationMatrix2D((width / 2, height / 2), angle, 1.0)
    turned = cv2.warpAffine(
        grey,
        matrix,
        (width, height),
        flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=255,
    )
    return turned.astype(np.uint8)


def _crop(grey: Grey) -> Grey:
    """``grey`` with dark scanner borders and everything more than ``CROP_PADDING`` outside
    its content cleared to white. A page with no content is kept as it is."""
    height, width = grey.shape
    # Specks don't count as content: a noisy scan is still cut to its text.
    ink = (denoise(_otsu(grey)) == 0).astype(np.uint8)
    count, labels, stats, _ = _components(ink)
    borders = [
        label
        for label in range(1, count)
        if _touches_edge(stats[label], width, height)
        and (
            stats[label][cv2.CC_STAT_WIDTH] > _BORDER * width
            or stats[label][cv2.CC_STAT_HEIGHT] > _BORDER * height
        )
    ]
    if borders:
        ink[np.isin(labels, borders)] = 0
    rows, columns = np.nonzero(ink)
    if len(rows) == 0:
        return grey
    top = max(int(rows.min()) - CROP_PADDING, 0)
    left = max(int(columns.min()) - CROP_PADDING, 0)
    bottom = min(int(rows.max()) + CROP_PADDING + 1, height)
    right = min(int(columns.max()) + CROP_PADDING + 1, width)
    cropped = np.full_like(grey, 255)
    cropped[top:bottom, left:right] = grey[top:bottom, left:right]
    if borders:
        cropped[np.isin(labels, borders)] = 255
    return cropped


def _touches_edge(stat: NDArray[np.int32], width: int, height: int) -> bool:
    x, y = int(stat[cv2.CC_STAT_LEFT]), int(stat[cv2.CC_STAT_TOP])
    w, h = int(stat[cv2.CC_STAT_WIDTH]), int(stat[cv2.CC_STAT_HEIGHT])
    return x == 0 or y == 0 or x + w >= width or y + h >= height
