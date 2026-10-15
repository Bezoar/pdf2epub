"""Recognising one page: image cleanup, the acceptance test and the retry ladder (OCR-R18
to OCR-R23).

The page render is uprighted (by the engine's orientation detection, when it has one),
deskewed and cropped once (``ocr.cleanup``). Then attempts run, each on its own variant
of the cleaned page:

1. ``baseline``: layout hint ``PAGE``, Otsu binarisation;
2. ``block``: layout hint ``BLOCK``, Otsu, if the last attempt's coverage was below
   ``C_MIN``;
3. ``sauvola``: Sauvola binarisation, if the last attempt's confidence was below the
   acceptance threshold;
4. ``sauvola+denoise``: Sauvola and denoise, if the last attempt's confidence is still
   below it.

Steps 3 and 4 keep the layout hint of the best attempt so far. An attempt is accepted when
its coverage is at least ``C_MIN`` and its page confidence at least ``P_MIN`` (or
``OcrOptions.min_confidence``). ``balanced`` stops at the first accepted attempt; ``fast``
runs the baseline only; ``best`` runs all four steps whatever they score. The best attempt
is the one with the highest (coverage, confidence).

The page budget (``OcrOptions.page_timeout``) covers the whole page: orientation
detection and every attempt. An attempt the engine fails counts as failed (no coverage,
no confidence) and the ladder goes on; one that runs out of budget ends the ladder.
"""

import time
from collections.abc import Mapping
from dataclasses import dataclass, replace

from PIL import Image

from pdf2epub.ocr.cleanup import Binarisation, Frame, prepare, variant_image
from pdf2epub.ocr.coverage import measure
from pdf2epub.ocr.engine import (
    Attempt,
    DetectsOrientation,
    EngineFailed,
    EngineTimeout,
    LayoutHint,
    OcrEngine,
    OcrPageResult,
    OcrRequest,
)
from pdf2epub.options import OcrOptions
from pdf2epub.reflow.build import OCR_FAILED, OCR_LOW_CONFIDENCE, OCR_TIMEOUT

C_MIN = 0.8
"""An attempt whose words' boxes have a lower coverage of the page's text-like ink has
dropped text (OCR-R16, OCR-R19)."""
P_MIN = 0.7
"""The page confidence an attempt needs to be accepted, unless ``min_confidence`` is set
(OCR-R19). Tesseract gives a clean 300 DPI page about 0.96."""


@dataclass(frozen=True)
class Variant:
    """One ladder step: what the engine is asked, and how the page is binarised."""

    name: str
    layout_hint: LayoutHint
    binarisation: Binarisation
    denoise: bool = False


BASELINE = Variant("baseline", "PAGE", "otsu")
BLOCK = Variant("block", "BLOCK", "otsu")
SAUVOLA = Variant("sauvola", "PAGE", "sauvola")
DENOISE = Variant("sauvola+denoise", "PAGE", "sauvola", denoise=True)


@dataclass(frozen=True)
class Recognition:
    """What the ladder made of a page."""

    result: OcrPageResult
    """The kept attempt's lines, confidence and coverage, with every attempt recorded;
    no lines if no attempt completed."""
    reason: str | None
    """None if the kept attempt was accepted; otherwise why the page falls back."""
    frame: Frame
    """Where the image the kept attempt read sits on the page."""


def threshold(options: OcrOptions) -> float:
    """The page confidence an attempt needs (OCR-R19)."""
    return P_MIN if options.min_confidence is None else options.min_confidence


def accepted(result: OcrPageResult, options: OcrOptions) -> bool:
    """Whether an attempt is accepted: coverage at least ``C_MIN`` and page confidence at
    least the threshold (OCR-R19)."""
    return result.coverage >= C_MIN and result.page_confidence >= threshold(options)


def recognise(
    engine: OcrEngine,
    image: Image.Image,
    dpi: int,
    options: OcrOptions,
    languages: str,
    engine_options: Mapping[str, str],
    deadline: float,
    osd: bool,
) -> Recognition:
    """Clean the page render ``image`` and run the ladder on it, by ``deadline``. ``osd``
    is the engine's ``Capabilities.osd``, asked once per conversion: whether its
    orientation detection may upright the page."""
    p_min = threshold(options)
    attempts: list[Attempt] = []
    completed: list[OcrPageResult] = []
    layouts: dict[int, LayoutHint] = {}
    timed_out = False
    rotation = 0
    if osd and isinstance(engine, DetectsOrientation):
        try:
            rotation = engine.orientation(image, dpi, deadline)
        except EngineTimeout:
            # The budget is spent: no attempt can run, so nothing is cleaned.
            return Recognition(OcrPageResult(lines=()), OCR_TIMEOUT, Frame(0, 0.0))
    prepared = prepare(image, rotation)

    def run(variant: Variant) -> OcrPageResult | None:
        """One attempt; None if it failed. Sets ``timed_out`` when the budget ran out."""
        nonlocal timed_out
        started = time.monotonic()
        if started >= deadline:
            timed_out = True
            return None
        request = OcrRequest(
            image=variant_image(prepared, variant.binarisation, variant.denoise),
            dpi=dpi,
            languages=languages,
            layout_hint=variant.layout_hint,
            deadline=deadline,
            engine_options=engine_options,
        )
        try:
            result = attempt(engine, request, variant.name)
        except (EngineTimeout, EngineFailed) as error:
            duration = round(time.monotonic() - started, 3)
            attempts.append(Attempt(variant.name, 0.0, 0.0, duration, completed=False))
            timed_out = timed_out or isinstance(error, EngineTimeout)
            return None
        attempts.extend(result.attempts)
        completed.append(result)
        layouts[id(result)] = variant.layout_hint
        return result

    def best() -> OcrPageResult | None:
        return max(completed, key=lambda r: (r.coverage, r.page_confidence), default=None)

    last = run(BASELINE)
    for step in () if options.quality == "fast" else (BLOCK, SAUVOLA, DENOISE):
        if timed_out:
            break
        if options.quality == "balanced":
            kept = best()
            if kept is not None and accepted(kept, options):
                break
            coverage_, confidence = (last.coverage, last.page_confidence) if last else (0, 0)
            if step is BLOCK and coverage_ >= C_MIN:
                continue
            if step is not BLOCK and confidence >= p_min:
                break
        if step is not BLOCK:
            # Sauvola keeps the layout hint of the best attempt so far.
            step = replace(step, layout_hint=layouts.get(id(best()), "PAGE"))
        last = run(step)
    kept = best()
    reason: str | None
    if kept is not None and accepted(kept, options):
        reason = None
    elif timed_out:
        reason = OCR_TIMEOUT
    elif kept is None:
        reason = OCR_FAILED
    else:
        reason = OCR_LOW_CONFIDENCE
    result = replace(kept or OcrPageResult(lines=()), attempts=tuple(attempts))
    return Recognition(result, reason, prepared.frame)


def attempt(engine: OcrEngine, request: OcrRequest, variant: str = "baseline") -> OcrPageResult:
    """One attempt, scored and recorded as ``variant``. ``EngineTimeout`` and
    ``EngineFailed`` pass through."""
    started = time.monotonic()
    result = engine.recognise(request)
    duration = time.monotonic() - started
    covered = coverage(request.image, result)
    record = Attempt(variant, result.page_confidence, covered, round(duration, 3))
    return replace(result, coverage=covered, attempts=(*result.attempts, record))


def coverage(image: Image.Image, result: OcrPageResult) -> float:
    """The coverage of the image's text-like ink by the recognised words' boxes (OCR-R16,
    ``ocr.coverage``)."""
    return measure(image, [(w.x0, w.top, w.x1, w.bottom) for w in result.words]).value
