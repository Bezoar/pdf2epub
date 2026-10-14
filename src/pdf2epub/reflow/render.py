"""Rendering whole pages with PDFium, for page-image fallbacks and the cover (RFL-R15,
RFL-R28), and encoding every image the book stores (RFL-R27).

A page is rendered so that its long edge is at most ``MAX_EDGE`` pixels (and never above
``MAX_DPI``), after its pixel count is checked against the decoded pixel limit (RFL-R6).
Interactive form fields are drawn as they appear; no script runs.

``encode`` is the one encoder for book images, page renders and the cover: downscaled to
a long edge of at most ``MAX_EDGE`` pixels, stored as PNG when grey, of few colours or
transparent, as text and line art are, and as JPEG otherwise.
"""

import io
import math
from collections.abc import Iterator, Sequence
from pathlib import Path

import pypdfium2 as pdfium
from PIL import Image, ImageChops

from pdf2epub.passwords import Secret
from pdf2epub.reflow.limits import ResourceLimitExceeded, check_image
from pdf2epub.reflow.model import ImageAsset

MAX_EDGE = 1600
"""The longest edge, in pixels, of any stored image (RFL-R27)."""
MAX_DPI = 300.0
JPEG_QUALITY = 85
# An image with at most this many colours is line art, stored as PNG.
_FEW_COLOURS = 256
# Colours are counted on a nearest-neighbour sample of at most this many pixels: it keeps
# the counting cheap on large images and, unlike smoothing, adds no new colours.
_SAMPLE_PIXELS = 1 << 20
_PDF_DPI = 72.0


def render_pages(
    path: Path, pages: Sequence[int], password: Secret | None = None
) -> Iterator[tuple[int, ImageAsset]]:
    """Render each of ``pages`` (1-based) of the PDF at ``path`` (opened with
    ``password`` if it needs one), in the order given.
    Raises ``ResourceLimitExceeded`` naming the page whose render would be too big."""
    if not pages:
        return
    document = pdfium.PdfDocument(
        path, password=password.reveal() if password is not None else None
    )
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


def render_grey(document: pdfium.PdfDocument, number: int, dpi: float) -> Image.Image:
    """Page ``number`` (1-based) of an open document as a greyscale image at ``dpi``, for
    OCR and the text-layer check. Raises ``ResourceLimitExceeded`` naming the page if
    the render would be too big."""
    page = document[number - 1]
    try:
        width, height = page.get_size()
        scale = dpi / _PDF_DPI
        size = (round(width * scale), round(height * scale))
        try:
            check_image(*size)
        except ResourceLimitExceeded as error:
            raise error.on_page(number) from None
        bitmap = page.render(scale=scale, grayscale=True)
        try:
            # PDFium rounds the bitmap up; the page is this many pixels at ``dpi``.
            image: Image.Image = bitmap.to_pil().convert("L").crop((0, 0, *size))
            return image
        finally:
            bitmap.close()
    finally:
        page.close()


def _render(page: pdfium.PdfPage) -> ImageAsset:
    width, height = page.get_size()
    scale = min(MAX_EDGE / max(width, height, 1.0), MAX_DPI / _PDF_DPI)
    check_image(math.ceil(width * scale), math.ceil(height * scale))
    bitmap = page.render(scale=scale)
    try:
        image = bitmap.to_pil().convert("RGB")
    finally:
        bitmap.close()
    return encode(image)


def encode(image: Image.Image) -> ImageAsset:
    """``image`` for the book (RFL-R27): downscaled so its long edge is at most
    ``MAX_EDGE`` pixels, as PNG when grey, of few colours or transparent, else as JPEG
    (quality 85). Whether it is line art is judged before downscaling blends its edges
    into new colours."""
    image = canonical(image)
    lossless = image.mode in ("L", "RGBA") or _sample(image).getcolors(_FEW_COLOURS) is not None
    width, height = image.size
    if max(width, height) > MAX_EDGE:
        scale = MAX_EDGE / max(width, height)
        size = (max(1, round(width * scale)), max(1, round(height * scale)))
        image = image.resize(size, Image.Resampling.LANCZOS)
    buffer = io.BytesIO()
    if lossless:
        image.save(buffer, format="PNG", compress_level=9)
        return ImageAsset(buffer.getvalue(), "image/png")
    image.save(buffer, format="JPEG", quality=JPEG_QUALITY)
    return ImageAsset(buffer.getvalue(), "image/jpeg")


def canonical(image: Image.Image) -> Image.Image:
    """``image``'s pixels in one fixed form, so the same pixels always compare equal: grey
    (``L``) when every pixel is grey, else colour (``RGB``), or colour with alpha
    (``RGBA``) only when something in it is transparent."""
    image = _plain(image)
    if image.mode == "RGB":
        grey = image.convert("L")
        if ImageChops.difference(image, grey.convert("RGB")).getbbox() is None:
            return grey
    return image


def _plain(image: Image.Image) -> Image.Image:
    """``image`` as grey (``L``), colour (``RGB``) or, only when something in it is
    transparent, colour with alpha (``RGBA``)."""
    transparent = image.mode in ("RGBA", "LA", "PA") or "transparency" in image.info
    if not transparent and image.mode == "1":
        return image.convert("L")
    if not transparent and image.mode in ("L", "RGB"):
        return image
    if transparent:
        image = image.convert("RGBA")
        lowest_alpha = image.getchannel("A").getextrema()[0]
        if isinstance(lowest_alpha, (int, float)) and lowest_alpha < 255:
            return image
    return image.convert("RGB")


def _sample(image: Image.Image) -> Image.Image:
    """``image``, or a nearest-neighbour sample of it of at most ``_SAMPLE_PIXELS``."""
    width, height = image.size
    if width * height <= _SAMPLE_PIXELS:
        return image
    scale = math.sqrt(_SAMPLE_PIXELS / (width * height))
    size = (max(1, int(width * scale)), max(1, int(height * scale)))
    return image.resize(size, Image.Resampling.NEAREST)
