"""Book images (RFL-R9): the raster images drawn on each page, with their places.

pdfium decodes each image object drawn directly on a page (``FPDFImageObj_GetBitmap``,
so every PDF image filter is handled), after its declared size passes the pixel limit
(RFL-R6). The image is stored as PNG.
"""

import io
import logging
from dataclasses import dataclass
from pathlib import Path

import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_c

from pdf2epub.reflow.limits import ResourceLimitExceeded, check_image
from pdf2epub.reflow.model import ImageAsset

log = logging.getLogger(__name__)

PNG = "image/png"


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
    document = pdfium.PdfDocument(path)
    try:
        for index in range(len(document)):
            page = document[index]
            try:
                placed = _page_images(page)
            except ResourceLimitExceeded as error:
                raise error.on_page(index + 1) from None
            finally:
                page.close()
            if placed:
                images[index + 1] = sorted(placed, key=lambda image: (image.top, image.x0))
    finally:
        document.close()
    return images


def _page_images(page: pdfium.PdfPage) -> list[PlacedImage]:
    height = page.get_height()
    placed: list[PlacedImage] = []
    for obj in page.get_objects(filter=[pdfium_c.FPDF_PAGEOBJ_IMAGE], max_depth=0):
        assert isinstance(obj, pdfium.PdfImage)
        width, rows = obj.get_px_size()
        check_image(width, rows)
        try:
            bitmap = obj.get_bitmap()
            picture = bitmap.to_pil()
        except pdfium.PdfiumError:
            log.debug("an image could not be decoded; it is left out", exc_info=True)
            continue
        if picture.mode not in ("L", "RGB", "RGBA"):
            picture = picture.convert("RGBA" if "A" in picture.mode else "RGB")
        buffer = io.BytesIO()
        picture.save(buffer, format="PNG", optimize=False, compress_level=9)
        left, bottom, right, top = obj.get_bounds()
        placed.append(
            PlacedImage(
                ImageAsset(buffer.getvalue(), PNG), left, right, height - top, height - bottom
            )
        )
    return placed
