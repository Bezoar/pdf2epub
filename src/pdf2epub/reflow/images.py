"""Book images (RFL-R9, RFL-R26, RFL-R27): the raster images drawn on each page, with
their places.

pdfium decodes each image object drawn on a page, directly or inside form XObjects
(``FPDFImageObj_GetBitmap``, so every PDF image filter is handled), after its declared
size passes the pixel limit (RFL-R6). Images with the same decoded pixels share one
asset, downscaled and re-encoded by ``reflow.render.encode``.
"""

import hashlib
import logging
from dataclasses import dataclass
from pathlib import Path

import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_c

from pdf2epub.passwords import Secret
from pdf2epub.reflow.limits import ResourceLimitExceeded, check_image
from pdf2epub.reflow.model import ImageAsset
from pdf2epub.reflow.render import canonical, encode

log = logging.getLogger(__name__)

# How deep to look into nested form XObjects for images.
_MAX_FORM_DEPTH = 15


@dataclass(frozen=True)
class PlacedImage:
    """An image on a page, in page coordinates measured from the top-left."""

    asset: ImageAsset
    x0: float
    x1: float
    top: float
    bottom: float


def read_images(path: Path, password: Secret | None = None) -> dict[int, list[PlacedImage]]:
    """The images on each page of ``path`` (opened with ``password`` if it needs one),
    by 1-based page index, top to bottom. Raises ``ResourceLimitExceeded`` for an image
    above the pixel limit."""
    images: dict[int, list[PlacedImage]] = {}
    seen: dict[str, ImageAsset] = {}
    """Each asset by the hash of its decoded pixels (RFL-R26)."""
    document = pdfium.PdfDocument(
        path, password=password.reveal() if password is not None else None
    )
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
        picture = canonical(picture)
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
