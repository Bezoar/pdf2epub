"""Rendering whole pages for page-image fallbacks (RFL-R15, RFL-R27) with PDFium.

A page is rendered so that its long edge is at most ``MAX_EDGE`` pixels (and never above
``MAX_DPI``), after its pixel count is checked against the decoded pixel limit (RFL-R6).
The render is stored as PNG when it is grey or has few colours, as text and line art do,
and as JPEG otherwise. Interactive form fields are drawn as they appear; no script runs.
"""

import io
import math
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path

import pypdfium2 as pdfium
from PIL import Image, ImageChops

from pdf2epub.reflow.limits import ResourceLimitExceeded, check_image

MAX_EDGE = 1600
"""The longest edge, in pixels, of any stored image (RFL-R27)."""
MAX_DPI = 300.0
JPEG_QUALITY = 85
# A render with at most this many colours is line art, stored as PNG.
_FEW_COLOURS = 256
_PDF_DPI = 72.0


@dataclass(frozen=True)
class Render:
    """An encoded page render."""

    data: bytes
    media_type: str
    extension: str


def render_pages(path: Path, pages: Sequence[int]) -> Iterator[tuple[int, Render]]:
    """Render each of ``pages`` (1-based) of the PDF at ``path``, in the order given.
    Raises ``ResourceLimitExceeded`` naming the page whose render would be too big."""
    if not pages:
        return
    document = pdfium.PdfDocument(path)
    try:
        for number in pages:
            page = document[number - 1]
            try:
                yield number, _render(page)
            except ResourceLimitExceeded as error:
                raise error.on_page(number) from None
            finally:
                page.close()
    finally:
        document.close()


def _render(page: pdfium.PdfPage) -> Render:
    width, height = page.get_size()
    scale = min(MAX_EDGE / max(width, height, 1.0), MAX_DPI / _PDF_DPI)
    check_image(math.ceil(width * scale), math.ceil(height * scale))
    bitmap = page.render(scale=scale)
    try:
        image = bitmap.to_pil().convert("RGB")
    finally:
        bitmap.close()
    return encode(image)


def encode(image: Image.Image) -> Render:
    """``image`` as PNG when grey or of few colours, else as JPEG (RFL-R27)."""
    grey = image.convert("L")
    if ImageChops.difference(image, grey.convert("RGB")).getbbox() is None:
        image = grey
    buffer = io.BytesIO()
    if image.mode == "L" or image.getcolors(_FEW_COLOURS) is not None:
        image.save(buffer, format="PNG", compress_level=9)
        return Render(buffer.getvalue(), "image/png", "png")
    image.save(buffer, format="JPEG", quality=JPEG_QUALITY)
    return Render(buffer.getvalue(), "image/jpeg", "jpg")
