"""The text-layer quality check (OCR-R5 to OCR-R9): whether a page's existing text layer is
trusted or rejected, page by page.

The layer is read with PDFium, character by character: its Unicode, whether PDFium found
no Unicode mapping for it (a Unicode-map error, as a font with no ToUnicode map gives),
its text render mode and its box. A layer is a **prior OCR layer** when most of its
characters are invisible (render mode 3, or 7: clip only), or when an image covers the
whole page under it; otherwise it is a **typeset text layer** (OCR-R6).

Three signals (OCR-R7), each against a threshold below:

1. garbage ratio: the share of non-space characters that are Unicode-map errors or
   garbage (``signals.is_garbage``: U+FFFD, Private Use Area, C0/C1 controls, letters of a
   script the OCR language doesn't use);
2. word plausibility: the share of word tokens in the language's wordlist, or that look
   like words when it has none (``signals.plausibility``); only judged on a page with at
   least ``MIN_TOKENS`` tokens;
3. coverage, for prior OCR layers only: the share of the rendered page's ink inside the
   layer's character boxes (OCR-R16's metric).

A page is rejected when any signal crosses its threshold; the reason reported is the first
failing one in the order garbled, implausible_words, low_coverage (OCR-R9, OP36).
"""

import ctypes
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_c

from pdf2epub.ocr.ladder import ink_coverage
from pdf2epub.ocr.signals import is_garbage, plausibility
from pdf2epub.passwords import Secret
from pdf2epub.reflow.extract import PageText
from pdf2epub.reflow.images import PlacedImage
from pdf2epub.reflow.render import render_grey

GARBLED, IMPLAUSIBLE_WORDS, LOW_COVERAGE = "garbled", "implausible_words", "low_coverage"
REASONS = (GARBLED, IMPLAUSIBLE_WORDS, LOW_COVERAGE)
"""The rejection reasons, in the order a page's reason is chosen (OP36)."""

# --- The thresholds (OCR-R8) ------------------------------------------------------------
# Internal constants with no option or flag, calibrated so that every must-trust fixture
# passes and every must-reject fixture fails (``scripts/calibrate_text_layer.py`` prints
# each signal's value on every fixture page).

MAX_GARBAGE_RATIO = 0.10
"""A layer with a larger share of garbage characters is ``garbled``."""
MIN_PLAUSIBILITY = 0.50
"""A layer with a smaller share of plausible words is ``implausible_words``."""
MIN_TOKENS = 20
"""Word plausibility is judged only on a page with at least this many word tokens."""
MIN_LAYER_COVERAGE = 0.70
"""A prior OCR layer whose character boxes hold a smaller share of the page's ink is
``low_coverage``."""

# --- Other constants --------------------------------------------------------------------

CHECK_DPI = 100
"""The resolution pages are rendered at to measure their ink."""
FULL_PAGE = 0.9
"""An image covering at least this share of the page is a full-page scan."""
_INVISIBLE = (3, 7)  # text render modes that draw nothing


@dataclass(frozen=True)
class LayerCheck:
    """The text-layer quality check's signals on one page."""

    prior_ocr: bool
    """The layer is a prior OCR layer, not a typeset one (OCR-R6)."""
    garbage: float
    plausibility: float
    tokens: int
    coverage: float | None
    """None for a typeset layer, where coverage is not a signal."""

    @property
    def reason(self) -> str | None:
        """Why the layer is rejected, or None if it is trusted."""
        if self.garbage > MAX_GARBAGE_RATIO:
            return GARBLED
        if self.tokens >= MIN_TOKENS and self.plausibility < MIN_PLAUSIBILITY:
            return IMPLAUSIBLE_WORDS
        if self.coverage is not None and self.coverage < MIN_LAYER_COVERAGE:
            return LOW_COVERAGE
        return None


def share(image: PlacedImage, page: PageText) -> float:
    """The share of the page an image covers, counting only the part on the page."""
    width = min(image.x1, page.width) - max(image.x0, 0.0)
    height = min(image.bottom, page.height) - max(image.top, 0.0)
    return max(width, 0.0) * max(height, 0.0) / max(page.width * page.height, 1.0)


def check_layers(
    path: Path,
    password: Secret | None,
    pages: Sequence[PageText],
    images: Mapping[int, Sequence[PlacedImage]],
    scripts: frozenset[str] | None,
    words: Collection[str] | None,
) -> dict[int, LayerCheck]:
    """Check the text layer of each of ``pages`` of the PDF at ``path``, in a book whose
    OCR language is written in ``scripts`` (not checked when None) and whose wordlist is
    ``words`` (None when the language has none)."""
    if not pages:
        return {}
    document = pdfium.PdfDocument(path, password=password.reveal() if password else None)
    try:
        return {
            page.page: _check(document, page, images.get(page.page, []), scripts, words)
            for page in pages
        }
    finally:
        document.close()


def _check(
    document: pdfium.PdfDocument,
    page: PageText,
    images: Sequence[PlacedImage],
    scripts: frozenset[str] | None,
    words: Collection[str] | None,
) -> LayerCheck:
    pdf_page = document[page.page - 1]
    try:
        _, _, _, top = pdf_page.get_bbox()
        textpage = pdf_page.get_textpage()
        try:
            raw = textpage.raw
            text = textpage.get_text_range()
            garbage = invisible = 0
            counted: list[int] = []  # the characters that count: not spaces, not generated
            modes: dict[int, bool] = {}  # by text object: whether it draws nothing
            for index in range(pdfium_c.FPDFText_CountChars(raw)):
                character = chr(pdfium_c.FPDFText_GetUnicode(raw, index))
                if character.isspace() or pdfium_c.FPDFText_IsGenerated(raw, index) == 1:
                    continue
                counted.append(index)
                if pdfium_c.FPDFText_HasUnicodeMapError(raw, index) == 1 or is_garbage(
                    character, scripts
                ):
                    garbage += 1
                obj = pdfium_c.FPDFText_GetTextObject(raw, index)
                key = ctypes.cast(obj, ctypes.c_void_p).value or 0
                if key not in modes:
                    modes[key] = bool(obj) and (
                        pdfium_c.FPDFTextObj_GetTextRenderMode(obj) in _INVISIBLE
                    )
                invisible += modes[key]
            scanned = any(share(image, page) >= FULL_PAGE for image in images)
            prior_ocr = bool(counted) and (2 * invisible >= len(counted) or scanned)
            boxes = [_box(raw, index, top) for index in counted] if prior_ocr else []
        finally:
            textpage.close()
    finally:
        pdf_page.close()
    share_plausible, count = plausibility(text, words)
    coverage = None
    if prior_ocr:
        image = render_grey(document, page.page, CHECK_DPI)
        coverage = ink_coverage(image, boxes)
    return LayerCheck(
        prior_ocr=prior_ocr,
        garbage=garbage / len(counted) if counted else 0.0,
        plausibility=share_plausible,
        tokens=count,
        coverage=coverage,
    )


def _box(textpage: object, index: int, top: float) -> tuple[float, float, float, float]:
    """Character ``index``'s box as (left, top, right, bottom) in pixels at ``CHECK_DPI``
    from the page's top-left corner."""
    left, right, bottom, upper = (ctypes.c_double() for _ in range(4))
    pdfium_c.FPDFText_GetCharBox(textpage, index, left, right, bottom, upper)
    scale = CHECK_DPI / 72
    return (
        left.value * scale,
        (top - upper.value) * scale,
        right.value * scale,
        (top - bottom.value) * scale,
    )
