"""Which pages are OCR'd (OCR-R1, OCR-R2, OCR-R4), running the engine on them, and turning
what it recognised into page text (OCR-R13, OCR-R16, OCR-R17, OCR-R28, OCR-R29, OCR-R31).

Under ``mode = "auto"`` a page with almost no text layer and a large image (a scan) is
OCR'd directly; a page with no text and no significant image is blank and left alone;
every other page keeps its text layer (the text-layer quality check comes with a later
ticket). Under ``always`` every page that isn't blank is OCR'd; under ``never`` none is.

Each OCR'd page is rendered at ``OCR_DPI`` and recognised once (the retry ladder comes
with a later ticket). Recognised lines replace the page's text layer, and the scan they
were read from stops being a book image. OCR'd text is one column for OCR, but a page whose
words fall in several columns is still found and kept in column order (RFL-R11, RFL-R15).
A result with no words leaves the page as it was: its text layer, if any, is kept
(OCR-R31), and a page without one contributes no text (OCR-R17).
"""

import logging
import time
from collections.abc import Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from statistics import median
from typing import Literal, Protocol

import cv2
import numpy as np
import pypdfium2 as pdfium
from PIL import Image

from pdf2epub.ocr import engine as ocr_engine
from pdf2epub.ocr.engine import Attempt, OcrEngine, OcrLine, OcrPageResult, OcrRequest
from pdf2epub.options import OcrOptions
from pdf2epub.passwords import Secret
from pdf2epub.reflow.columns import Gutter, Piece, column_of, find_gutters, split
from pdf2epub.reflow.extract import Line, PageText, normalise
from pdf2epub.reflow.images import PlacedImage
from pdf2epub.reflow.limits import ResourceLimitExceeded, check_image
from pdf2epub.results import OcrSummary

log = logging.getLogger(__name__)

Trigger = Literal["no_text_layer", "text_layer_rejected", "forced"]

OCR_DPI = 300
"""The resolution pages are rendered at for OCR."""
ALMOST_NO_TEXT = 0.01
"""A text layer whose lines cover at most this share of the page is almost none (OCR-R1)."""
LARGE_IMAGE = 0.5
"""An image covering at least this share of the page is a large one: a scan (OCR-R1)."""
SIGNIFICANT_IMAGE = 0.01
"""An image covering less than this share of the page is insignificant (OCR-R1)."""
DEFAULT_LANGUAGES = "eng"
# Recognised lines whose heights are within this share of the page's median line height
# are body lines, of one size; only lines clearly taller stand out (RFL-R21).
_SAME_HEIGHT = 0.2
_PDF_DPI = 72.0


class Reporter(Protocol):
    def progress(self, stage: str, done: int, of: int, **fields: object) -> None: ...


@dataclass(frozen=True)
class OcrOutcome:
    """The pages after OCR: their text, their book images and the OCR summary."""

    pages: list[PageText]
    images: dict[int, list[PlacedImage]]
    summary: OcrSummary | None


def route(page: PageText, images: Sequence[PlacedImage], mode: str) -> Trigger | None:
    """Why ``page`` is OCR'd, or None if it isn't."""
    area = max(page.width * page.height, 1.0)
    text = sum((line.x1 - line.x0) * (line.bottom - line.top) for line in page.lines) / area
    image = max((_share(placed, page) for placed in images), default=0.0)
    blank = not page.lines and image < SIGNIFICANT_IMAGE
    if blank or mode == "never":
        return None
    if mode == "always":
        return "forced"
    if text <= ALMOST_NO_TEXT and image >= LARGE_IMAGE:
        return "no_text_layer"
    return None


def _share(image: PlacedImage, page: PageText) -> float:
    """The share of the page an image covers, counting only the part on the page."""
    width = min(image.x1, page.width) - max(image.x0, 0.0)
    height = min(image.bottom, page.height) - max(image.top, 0.0)
    return max(width, 0.0) * max(height, 0.0) / max(page.width * page.height, 1.0)


def ocr_pages(
    path: Path,
    password: Secret | None,
    pages: list[PageText],
    images: dict[int, list[PlacedImage]],
    options: OcrOptions,
    reporter: Reporter,
) -> OcrOutcome:
    """OCR the pages that need it, reporting each as it finishes (OCR-R29)."""
    routed = [
        (page, trigger)
        for page in pages
        if (trigger := route(page, images.get(page.page, []), options.mode)) is not None
    ]
    engine = ocr_engine.load_engine(options) if routed else None
    if engine is None:
        return OcrOutcome(pages, images, None)
    languages = options.languages or DEFAULT_LANGUAGES
    engine_options = {
        key.removeprefix("tesseract."): value for key, value in options.engine_options.items()
    }
    replaced: dict[int, PageText] = {}
    kept_images = dict(images)
    document = pdfium.PdfDocument(path, password=password.reveal() if password else None)
    try:
        for done, (page, trigger) in enumerate(routed, start=1):
            image = _render(document, page.page)
            request = OcrRequest(
                image=image,
                dpi=OCR_DPI,
                languages=languages,
                layout_hint="PAGE",
                deadline=time.monotonic() + options.page_timeout,
                engine_options=engine_options,
            )
            result = _recognise(engine, request)
            text = page_text(page, result, OCR_DPI)
            if text is not None:
                replaced[page.page] = text
                kept_images[page.page] = [
                    placed
                    for placed in images.get(page.page, [])
                    if _share(placed, page) < LARGE_IMAGE
                ]
            reporter.progress(
                "ocr",
                done,
                len(routed),
                page=page.page,
                trigger=trigger,
                confidence=round(result.page_confidence, 4),
                coverage=round(result.coverage, 4),
                attempts=len(result.attempts),
                fell_back=text is not None and text.columns > 1,
            )
    finally:
        document.close()
    capabilities = engine.capabilities()
    summary = OcrSummary(
        engine=capabilities.name,
        engine_version=capabilities.version,
        languages=languages.split("+"),
        quality=options.quality,
    )
    pages = [replaced.get(page.page, page) for page in pages]
    return OcrOutcome(pages, {k: v for k, v in kept_images.items() if v}, summary)


def _render(document: pdfium.PdfDocument, number: int) -> Image.Image:
    """Page ``number`` (1-based) as a greyscale image at ``OCR_DPI``."""
    page = document[number - 1]
    try:
        width, height = page.get_size()
        scale = OCR_DPI / _PDF_DPI
        size = (round(width * scale), round(height * scale))
        try:
            check_image(*size)
        except ResourceLimitExceeded as error:
            raise error.on_page(number) from None
        bitmap = page.render(scale=scale, grayscale=True)
        try:
            # PDFium rounds the bitmap up; the page is this many pixels at OCR_DPI.
            image: Image.Image = bitmap.to_pil().convert("L").crop((0, 0, *size))
            return image
        finally:
            bitmap.close()
    finally:
        page.close()


def _recognise(engine: OcrEngine, request: OcrRequest) -> OcrPageResult:
    """One attempt, scored and recorded."""
    started = time.monotonic()
    result = engine.recognise(request)
    duration = time.monotonic() - started
    covered = coverage(request.image, result)
    attempt = Attempt("baseline", result.page_confidence, covered, round(duration, 3))
    return replace(result, coverage=covered, attempts=(*result.attempts, attempt))


def coverage(image: Image.Image, result: OcrPageResult) -> float:
    """The share of the image's ink (dark pixels after Otsu binarisation) inside the boxes
    of the recognised words (OCR-R16); 1 for an image with no ink."""
    grey = np.asarray(image.convert("L"), dtype=np.uint8)
    _, binary = cv2.threshold(grey, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    ink = binary == 0
    total = int(ink.sum())
    if total == 0 or ink.all():
        return 1.0 if total == 0 else 0.0
    boxes = np.zeros_like(ink)
    rows, columns = ink.shape
    for word in result.words:
        top, bottom = max(int(word.top), 0), min(int(np.ceil(word.bottom)), rows)
        left, right = max(int(word.x0), 0), min(int(np.ceil(word.x1)), columns)
        boxes[top:bottom, left:right] = True
    return int((ink & boxes).sum()) / total


def page_text(page: PageText, result: OcrPageResult, dpi: int) -> PageText | None:
    """``page`` with the recognised lines as its text, or None if nothing was recognised.
    Lines are in reading order, in column order on a page set in columns."""
    recognised = [line for line in result.lines if any(w.text.strip() for w in line.words)]
    if not recognised:
        return None
    scale = _PDF_DPI / dpi
    heights = [line.height for line in recognised]
    body = median(heights)
    pieces = [_piece(line, scale, _size(line.height, body) * scale) for line in recognised]
    gutters = find_gutters(pieces)
    lines: list[tuple[Line, int | None]] = []
    for line, piece in zip(recognised, pieces, strict=True):
        for group in split(piece, gutters) if gutters else [list(range(len(line.words)))]:
            words = [line.words[index] for index in group]
            part = _piece(OcrLine(tuple(words), line.height), scale, piece.size)
            text = normalise(" ".join(w.text.strip() for w in words if w.text.strip()))
            if text:
                ocr_line = Line(text, part.x0, part.x1, part.top, part.bottom, piece.size)
                lines.append((ocr_line, column_of(part, gutters) if gutters else 0))
    return replace(page, lines=_reading_order(lines, gutters), columns=len(gutters) + 1, ocr=True)


def _size(height: float, body: float) -> float:
    """A line's size: the body lines' median height, unless it is clearly taller or
    shorter (RFL-R21)."""
    return body if abs(height - body) <= _SAME_HEIGHT * body else height


def _piece(line: OcrLine, scale: float, size: float) -> Piece:
    words = [word for word in line.words if word.text.strip()]
    return Piece(
        [(word.x0 * scale, word.x1 * scale) for word in words],
        min(word.top for word in words) * scale,
        max(word.bottom for word in words) * scale,
        size,
    )


def _reading_order(lines: list[tuple[Line, int | None]], gutters: list[Gutter]) -> list[Line]:
    """Top to bottom; on a page set in columns, each part of the page between lines across
    the columns is read column by column, left to right (RFL-R15)."""
    if not gutters:
        return sorted((line for line, _ in lines), key=lambda line: (line.top, line.x0))
    across = sorted((line for line, column in lines if column is None), key=lambda li: li.top)
    ordered: list[Line] = []
    for section in range(len(across) + 1):
        for column in range(len(gutters) + 1):
            ordered.extend(
                sorted(
                    (
                        line
                        for line, index in lines
                        if index == column and sum(a.top < line.top for a in across) == section
                    ),
                    key=lambda line: (line.top, line.x0),
                )
            )
        if section < len(across):
            ordered.append(across[section])
    return ordered
