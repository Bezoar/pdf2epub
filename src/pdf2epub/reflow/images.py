"""Book images (RFL-R9, RFL-R26, RFL-R27): the raster images drawn on each page, with
their places, and the encoding every image in the book goes through.

pdfium decodes each image object drawn on a page, directly or inside form XObjects
(``FPDFImageObj_GetBitmap``, so every PDF image filter is handled), after its declared
size passes the pixel limit (RFL-R6). Images with the same decoded pixels share one
asset. ``encode`` downscales and re-encodes any picture for the book: book images, the
cover and page renders alike.
"""

import hashlib
import io
import logging
from dataclasses import dataclass
from pathlib import Path

import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_c
from PIL import Image

from pdf2epub.reflow.limits import ResourceLimitExceeded, check_image
from pdf2epub.reflow.model import ImageAsset

log = logging.getLogger(__name__)

PNG, JPEG = "image/png", "image/jpeg"
MAX_EDGE = 1600
"""The longest edge, in pixels, of any image in the book (RFL-R27)."""
JPEG_QUALITY = 85
FEW_COLOURS = 256
"""A picture with at most this many colours is line art or flat colour: kept as PNG."""

# How deep to look into nested form XObjects for images.
_MAX_FORM_DEPTH = 15


def encode(picture: Image.Image) -> ImageAsset:
    """``picture`` for the book (RFL-R27): downscaled so its long edge is at most
    ``MAX_EDGE`` pixels, then JPEG (quality 85) when photographic, PNG when it has few
    colours or transparency. Whether it is photographic is judged on the picture as
    given, before downscaling blends its edges into new colours."""
    picture = _plain(picture)
    lossless = picture.mode == "RGBA" or picture.getcolors(FEW_COLOURS) is not None
    width, height = picture.size
    if max(width, height) > MAX_EDGE:
        scale = MAX_EDGE / max(width, height)
        size = (max(1, round(width * scale)), max(1, round(height * scale)))
        picture = picture.resize(size, Image.Resampling.LANCZOS)
    buffer = io.BytesIO()
    if lossless:
        picture.save(buffer, format="PNG", optimize=False, compress_level=9)
        return ImageAsset(buffer.getvalue(), PNG)
    picture.save(buffer, format="JPEG", quality=JPEG_QUALITY, optimize=False, progressive=False)
    return ImageAsset(buffer.getvalue(), JPEG)


def _plain(picture: Image.Image) -> Image.Image:
    """``picture`` as grey (``L``), colour (``RGB``) or, only when something in it is
    transparent, colour with alpha (``RGBA``)."""
    if picture.mode == "1":
        return picture.convert("L")
    if picture.mode in ("L", "RGB"):
        return picture
    transparent = picture.mode in ("RGBA", "LA", "PA") or "transparency" in picture.info
    if transparent:
        picture = picture.convert("RGBA")
        lowest_alpha = picture.getchannel("A").getextrema()[0]
        if isinstance(lowest_alpha, int | float) and lowest_alpha < 255:
            return picture
    return picture.convert("RGB")


def render_page(document: pdfium.PdfDocument, index: int) -> Image.Image:
    """A render of page ``index`` (0-based) whose long edge is ``MAX_EDGE`` pixels,
    within the pixel limit (RFL-R6)."""
    page = document[index]
    try:
        width, height = page.get_size()
        scale = MAX_EDGE / max(width, height, 1e-6)
        check_image(round(width * scale), round(height * scale))
        picture: Image.Image = page.render(scale=scale).to_pil()
        return picture.convert("RGB")
    except ResourceLimitExceeded as error:
        raise error.on_page(index + 1) from None
    finally:
        page.close()


@dataclass(frozen=True)
class PlacedImage:
    """An image on a page, in page coordinates measured from the top-left."""

    asset: ImageAsset
    x0: float
    x1: float
    top: float
    bottom: float


def read_images(path: Path) -> dict[int, list[PlacedImage]]:
    """The images on each page of ``path``, by 1-based page index, top to bottom. Raises
    ``ResourceLimitExceeded`` for an image above the pixel limit."""
    images: dict[int, list[PlacedImage]] = {}
    seen: dict[str, ImageAsset] = {}
    """Each asset by the hash of its decoded pixels (RFL-R26)."""
    document = pdfium.PdfDocument(path)
    try:
        for index in range(len(document)):
            page = document[index]
            try:
                placed = _page_images(page, seen)
            except ResourceLimitExceeded as error:
                raise error.on_page(index + 1) from None
            finally:
                page.close()
            if placed:
                images[index + 1] = sorted(placed, key=lambda image: (image.top, image.x0))
    finally:
        document.close()
    return images


def _page_images(page: pdfium.PdfPage, seen: dict[str, ImageAsset]) -> list[PlacedImage]:
    height = page.get_height()
    placed: list[PlacedImage] = []
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
        try:
            picture = obj.get_bitmap().to_pil()
        except pdfium.PdfiumError:
            log.debug("an image could not be decoded; it is left out", exc_info=True)
            continue
        key = hashlib.sha256(
            f"{picture.mode} {picture.size}".encode() + picture.tobytes()
        ).hexdigest()
        asset = seen.get(key)
        if asset is None:
            asset = seen[key] = encode(picture)
        left, bottom, right, top = obj.get_bounds()
        if forms:
            # Bounds inside a form are in the form's space: map them onto the page.
            xs, ys = zip(
                *(forms[-1].on_point(x, y) for x in (left, right) for y in (bottom, top)),
                strict=True,
            )
            left, right, bottom, top = min(xs), max(xs), min(ys), max(ys)
        placed.append(PlacedImage(asset, left, right, height - top, height - bottom))
    return placed
