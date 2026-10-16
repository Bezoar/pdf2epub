"""Book images (RFL-R9, RFL-R26, RFL-R27): the raster images drawn on each page, with
their places, taken as the page shows them.

pdfium decodes each image object drawn on a page, directly or inside form XObjects,
after its declared size passes the pixel limit (RFL-R6). Positions are in the visible
page's frame (its CropBox, turned as ``/Rotate`` says, measured from the top-left), the
frame the text and OCR lines use. An image wholly or almost wholly outside the visible
page is left out, and one partly outside is cut to the part that shows.

An image with a mask (a soft mask, a stencil, a colour key) is taken as rendered, with
its mask applied (``FPDFImageObj_GetRenderedBitmap``): its own pixels outside the mask
are often junk, such as the text colour smeared over the whole page by scanning
software that draws each page as a background image under a masked foreground. A
masked image drawn over an earlier image is composited onto it, so the two are one
picture, as on the page. Other images keep their decoded pixels
(``FPDFImageObj_GetBitmap``, so every PDF image filter is handled) unless they must be
cut. Images with the same pixels share one asset, downscaled and re-encoded by
``reflow.render.encode``; anything still transparent is put on white first unless the
image background is ``transparent`` (RFL-R27).
"""

import hashlib
import logging
import math
from collections.abc import Collection
from dataclasses import dataclass
from pathlib import Path

import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_c
from PIL import Image

from pdf2epub.options import ImageBackground
from pdf2epub.passwords import Secret
from pdf2epub.reflow.limits import ResourceLimitExceeded, check_image
from pdf2epub.reflow.model import ImageAsset
from pdf2epub.reflow.render import canonical, encode

log = logging.getLogger(__name__)

# How deep to look into nested form XObjects for images.
_MAX_FORM_DEPTH = 15
# An image with less than this share of its area on the visible page is left out.
MIN_VISIBLE = 0.05
# A rendered image is masked when more of it is see-through (alpha below half) than its
# shape explains (a turned image's corners), by more than this share.
_MASKED_EXCESS = 0.02

Box = tuple[float, float, float, float]
"""(left, top, right, bottom) in the visible page's frame, in points."""


@dataclass(frozen=True)
class PlacedImage:
    """An image on a page, in the visible page's coordinates measured from the top-left."""

    asset: ImageAsset
    x0: float
    x1: float
    top: float
    bottom: float


def read_images(
    path: Path,
    password: Secret | None = None,
    skip: Collection[int] = (),
    *,
    background: ImageBackground,
) -> dict[int, list[PlacedImage]]:
    """The images on each page of ``path`` (opened with ``password`` if it needs one),
    by 1-based page index, top to bottom, leaving out the pages in ``skip`` (unreadable
    pages, RFL-R37), with transparency kept or put on white as ``background`` says
    (RFL-R27). Raises ``ResourceLimitExceeded`` for an image above the pixel limit."""
    images: dict[int, list[PlacedImage]] = {}
    seen: dict[str, ImageAsset] = {}
    """Each asset by the hash of its pixels (RFL-R26)."""
    document = pdfium.PdfDocument(
        path, password=password.reveal() if password is not None else None
    )
    try:
        for index in range(len(document)):
            if index + 1 in skip:
                continue
            page = document[index]
            try:
                placed = _page_images(page, seen, background)
            except ResourceLimitExceeded as error:
                raise error.on_page(index + 1) from None
            finally:
                page.close()
            if placed:
                images[index + 1] = sorted(placed, key=lambda image: (image.top, image.x0))
    finally:
        document.close()
    return images


@dataclass(frozen=True)
class _Frame:
    """The visible page: its box in page space and its turn (clockwise degrees)."""

    left: float
    bottom: float
    right: float
    top: float
    rotation: int

    @classmethod
    def of(cls, page: pdfium.PdfPage) -> "_Frame":
        left, bottom, right, top = page.get_bbox()
        return cls(left, bottom, right, top, page.get_rotation() % 360)

    @property
    def size(self) -> tuple[float, float]:
        width, height = self.right - self.left, self.top - self.bottom
        return (height, width) if self.rotation in (90, 270) else (width, height)

    def point(self, x: float, y: float) -> tuple[float, float]:
        """Page-space ``(x, y)`` as (across, down) from the visible page's top-left."""
        if self.rotation == 90:
            return y - self.bottom, x - self.left
        if self.rotation == 180:
            return self.right - x, y - self.bottom
        if self.rotation == 270:
            return self.top - y, self.right - x
        return x - self.left, self.top - y

    def box(self, left: float, bottom: float, right: float, top: float) -> Box:
        xs, ys = zip(*(self.point(x, y) for x in (left, right) for y in (bottom, top)), strict=True)
        return min(xs), min(ys), max(xs), max(ys)


@dataclass(eq=False)
class _Layer:
    picture: Image.Image
    box: Box
    masked: bool


def _page_images(
    page: pdfium.PdfPage, seen: dict[str, ImageAsset], background: ImageBackground
) -> list[PlacedImage]:
    frame = _Frame.of(page)
    visible: Box = (0.0, 0.0, *frame.size)
    groups: list[list[_Layer]] = []
    """The pictures on the page: each a stack of layers, the first drawn first."""
    forms: list[pdfium.PdfMatrix] = []
    """The page matrix of each enclosing form XObject, outermost first."""
    for obj in page.get_objects(max_depth=_MAX_FORM_DEPTH):
        del forms[obj.level :]
        if obj.type == pdfium_c.FPDF_PAGEOBJ_FORM:
            matrix = obj.get_matrix()
            forms.append(matrix.multiply(forms[-1]) if forms else matrix)
            continue
        if not isinstance(obj, pdfium.PdfImage):
            continue
        width, rows = obj.get_px_size()
        check_image(width, rows)
        left, bottom, right, top = obj.get_bounds()
        if forms:
            # Bounds inside a form are in the form's space: map them onto the page.
            xs, ys = zip(
                *(forms[-1].on_point(x, y) for x in (left, right) for y in (bottom, top)),
                strict=True,
            )
            left, right, bottom, top = min(xs), max(xs), min(ys), max(ys)
        box = frame.box(left, bottom, right, top)
        shown = _area(_intersection(box, visible)) / max(_area(box), 1e-9)
        if shown < MIN_VISIBLE:
            continue
        try:
            layer = _layer(obj, box, frame.rotation, whole=_intersection(box, visible) == box)
        except pdfium.PdfiumError:
            log.debug("an image could not be decoded; it is left out", exc_info=True)
            continue
        # A masked image over earlier pictures is composited onto them (all of them it
        # overlaps become one).
        under = [g for g in groups if layer.masked and _area(_intersection(box, _union(g))) > 0]
        if under:
            groups = [g for g in groups if not any(g is u for u in under)]
            groups.append([*(below for group in under for below in group), layer])
        else:
            groups.append([layer])
    placed: list[PlacedImage] = []
    for group in groups:
        picture, box = _composite(group)
        picture, box = _cut(picture, box, visible)
        picture = canonical(picture, background)
        key = hashlib.sha256(
            f"{picture.mode} {picture.size}".encode() + picture.tobytes()
        ).hexdigest()
        asset = seen.get(key)
        if asset is None:
            asset = seen[key] = encode(picture, background)
        placed.append(PlacedImage(asset, box[0], box[2], box[1], box[3]))
    return placed


def _layer(obj: pdfium.PdfImage, box: Box, rotation: int, whole: bool) -> _Layer:
    """The image as a layer: as rendered when it is masked or must be cut, else its
    decoded pixels."""
    a, b, c, d, _, _ = obj.get_matrix().get()
    # The rendered bitmap covers the image's bounding box at its own resolution: check
    # that, not just its declared size, against the pixel limit.
    width, rows = obj.get_px_size()
    shape = abs(a * d - b * c)
    spread = (abs(a) + abs(c)) * (abs(b) + abs(d))
    check_image(math.ceil(width * rows * spread / max(shape, 1e-9)), 1)
    rendered = obj.get_bitmap(render=True).to_pil().convert("RGBA")
    # A turned image's corners are see-through; any more than that is a mask.
    corners = 1.0 - shape / max(spread, 1e-9)
    masked = _see_through(rendered) > corners + _MASKED_EXCESS
    if masked:
        return _Layer(_turned(rendered, rotation), box, True)
    if whole:
        return _Layer(_turned(obj.get_bitmap().to_pil(), rotation), box, False)
    flat = Image.new("RGBA", rendered.size, (255, 255, 255, 255))
    flat.alpha_composite(rendered)
    return _Layer(_turned(flat.convert("RGB"), rotation), box, False)


def _see_through(picture: Image.Image) -> float:
    """The share of ``picture``'s pixels, inside a one-pixel edge, that are mostly
    transparent."""
    width, height = picture.size
    if width > 2 and height > 2:
        picture = picture.crop((1, 1, width - 1, height - 1))
    histogram = picture.getchannel("A").histogram()
    return sum(histogram[:128]) / max(sum(histogram), 1)


def _turned(picture: Image.Image, rotation: int) -> Image.Image:
    """``picture`` turned clockwise by the page's ``rotation``, as the page shows it."""
    return picture.rotate(-rotation, expand=True) if rotation else picture


def _composite(group: list[_Layer]) -> tuple[Image.Image, Box]:
    """The group's layers drawn in order onto one picture covering all of them, at the
    finest resolution among them."""
    if len(group) == 1:
        return group[0].picture, group[0].box
    box = _union(group)
    scale_x = max(layer.picture.width / max(layer.box[2] - layer.box[0], 1e-9) for layer in group)
    scale_y = max(layer.picture.height / max(layer.box[3] - layer.box[1], 1e-9) for layer in group)
    size = (
        max(1, math.ceil((box[2] - box[0]) * scale_x)),
        max(1, math.ceil((box[3] - box[1]) * scale_y)),
    )
    check_image(*size)
    canvas = Image.new("RGBA", size, (0, 0, 0, 0))
    for layer in group:
        left, top, right, bottom = layer.box
        target = (
            max(1, round((right - left) * scale_x)),
            max(1, round((bottom - top) * scale_y)),
        )
        picture = layer.picture.convert("RGBA")
        if picture.size != target:
            picture = picture.resize(target, Image.Resampling.LANCZOS)
        offset = (round((left - box[0]) * scale_x), round((top - box[1]) * scale_y))
        canvas.alpha_composite(picture, offset)
    return canvas, box


def _cut(picture: Image.Image, box: Box, visible: Box) -> tuple[Image.Image, Box]:
    """``picture``, drawn at ``box``, cut to the part inside ``visible``: every pixel that
    shows at all is kept, so the cut is never empty. A masked picture keeps its
    transparency, as an uncut one does (RFL-R27)."""
    shown = _intersection(box, visible)
    if shown == box:
        return picture, box
    width, height = box[2] - box[0], box[3] - box[1]
    scale_x, scale_y = picture.width / max(width, 1e-9), picture.height / max(height, 1e-9)
    left = min(math.floor((shown[0] - box[0]) * scale_x), picture.width - 1)
    top = min(math.floor((shown[1] - box[1]) * scale_y), picture.height - 1)
    right = max(math.ceil((shown[2] - box[0]) * scale_x), left + 1)
    bottom = max(math.ceil((shown[3] - box[1]) * scale_y), top + 1)
    crop = (max(left, 0), max(top, 0), min(right, picture.width), min(bottom, picture.height))
    return picture.crop(crop), shown


def _intersection(a: Box, b: Box) -> Box:
    left, top = max(a[0], b[0]), max(a[1], b[1])
    return left, top, max(left, min(a[2], b[2])), max(top, min(a[3], b[3]))


def _union(group: list[_Layer]) -> Box:
    return (
        min(layer.box[0] for layer in group),
        min(layer.box[1] for layer in group),
        max(layer.box[2] for layer in group),
        max(layer.box[3] for layer in group),
    )


def _area(box: Box) -> float:
    return max(box[2] - box[0], 0.0) * max(box[3] - box[1], 0.0)
