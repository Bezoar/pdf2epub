"""Which pages are OCR'd (OCR-R1 to OCR-R4, OCR-R9), running the engine on them, and
turning what it recognised into page text (OCR-R10, OCR-R13, OCR-R17, OCR-R28, OCR-R29,
OCR-R31).

Under ``mode = "auto"`` a page with almost no text layer and a large image (a scan) is
OCR'd directly; a page with no text and no significant image is blank and left alone;
every other page goes through the text-layer quality check (``ocr.textlayer``) and is
OCR'd only if its layer is rejected, each rejection reported in a ``text_layer_rejected``
issue. Under ``always`` every page that isn't blank is OCR'd. Under ``never`` none is: a
page whose layer is rejected, or that would be OCR'd directly, becomes a page image with
reason ``bad_text_layer``. A layer rejected as garbled is never kept as hidden text.

Each OCR'd page is rendered at ``OCR_DPI``, cleaned and recognised through the retry
ladder (``ocr.ladder``). The lines of an accepted attempt replace the page's text layer,
and the scan they were read from stops being a book image. OCR'd text is one column for
OCR, but a page whose words fall in several columns is still found and kept in column
order (RFL-R11, RFL-R15). When every attempt read nothing the page is left as it was: its
text layer, if any, is kept (OCR-R31), and a page without one contributes no text
(OCR-R17); if its layer was rejected, it becomes a page image with no hidden text
(OCR-R31). Otherwise a page with no accepted attempt becomes a page image with reason
``ocr_low_confidence``, ``ocr_timeout`` or ``ocr_failed`` (OCR-R20, OCR-R22, OCR-R23),
its hidden text the better of the best attempt and its own text layer (OCR-R10); timed-out
and failed pages are also listed in an issue of that code.
"""

import logging
import time
from collections.abc import Collection, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from statistics import median
from typing import Any, Literal, Protocol

import pypdfium2 as pdfium

from pdf2epub.issues import Issue, IssueCode
from pdf2epub.ocr import engine as ocr_engine
from pdf2epub.ocr import ladder
from pdf2epub.ocr.cleanup import Frame
from pdf2epub.ocr.engine import EngineProbe, OcrLine, OcrPageResult
from pdf2epub.ocr.ladder import attempt as attempt
from pdf2epub.ocr.ladder import coverage as coverage
from pdf2epub.ocr.languages import ocr_languages
from pdf2epub.ocr.signals import garbage_ratio, language_scripts, plausibility
from pdf2epub.ocr.textlayer import (
    FULL_PAGE,
    GARBLED,
    IMPLAUSIBLE_WORDS,
    LOW_COVERAGE,
    REASONS,
    LayerCheck,
    check_layers,
    share,
)
from pdf2epub.options import ConversionOptions
from pdf2epub.passwords import Secret
from pdf2epub.reflow.build import (
    BAD_TEXT_LAYER,
    OCR_FAILED,
    OCR_LOW_CONFIDENCE,
    OCR_TIMEOUT,
    OCR_UNAVAILABLE,
    fallback_reason,
)
from pdf2epub.reflow.columns import Gutter, Piece, column_of, find_gutters, split
from pdf2epub.reflow.extract import Line, PageText, normalise
from pdf2epub.reflow.images import PlacedImage
from pdf2epub.reflow.metadata import DEFAULT_LANGUAGE
from pdf2epub.reflow.render import render_grey
from pdf2epub.reflow.wordlists import wordlist
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
# Recognised lines whose heights are within this share of the page's median line height
# are body lines, of one size; only lines clearly taller stand out (RFL-R21).
_SAME_HEIGHT = 0.2
_PDF_DPI = 72.0
_REJECTION_MESSAGES = {
    GARBLED: "The text layer of these pages is garbled (characters with no Unicode mapping, "
    "or not text), so it was not used.",
    IMPLAUSIBLE_WORDS: "The text layer of these pages is mostly not words, so it was not used.",
    LOW_COVERAGE: "The text layer of these pages covers only part of the printed text, so it "
    "was not used.",
}
_FAILURE_MESSAGES = {
    OCR_TIMEOUT: "OCR on these pages ran past the per-page time budget; they fell back to "
    "page images.",
    OCR_FAILED: "The OCR engine crashed or exited with an error on these pages; they fell "
    "back to page images.",
}


class Progress(Protocol):
    """Reports a page done in a stage; a page boundary, where a cancelled batch stops."""

    def __call__(self, stage: str, done: int, of: int, **fields: Any) -> None: ...


@dataclass(frozen=True)
class OcrOutcome:
    """The pages after OCR: their text, their book images, the OCR summary and the
    issues OCR raised."""

    pages: list[PageText]
    images: dict[int, list[PlacedImage]]
    summary: OcrSummary | None
    issues: list[Issue] = field(default_factory=list)


def route(
    page: PageText, images: Sequence[PlacedImage], mode: str, rejected: bool = False
) -> Trigger | None:
    """Why ``page`` is OCR'd, or None if it isn't. ``rejected``: the text-layer quality
    check rejected the page's layer."""
    if _blank(page, images) or mode == "never":
        return None
    if mode == "always":
        return "forced"
    if ocr_directly(page, images):
        return "no_text_layer"
    return "text_layer_rejected" if rejected else None


def _blank(page: PageText, images: Sequence[PlacedImage]) -> bool:
    """No text and no significant image (OCR-R1)."""
    return not page.lines and max((share(i, page) for i in images), default=0.0) < SIGNIFICANT_IMAGE


def ocr_directly(page: PageText, images: Sequence[PlacedImage]) -> bool:
    """Almost no text layer and a large image: a page OCR'd directly (OCR-R1)."""
    area = max(page.width * page.height, 1.0)
    text = sum((line.x1 - line.x0) * (line.bottom - line.top) for line in page.lines) / area
    image = max((share(placed, page) for placed in images), default=0.0)
    return text <= ALMOST_NO_TEXT and image >= LARGE_IMAGE


def ocr_pages(
    path: Path,
    password: Secret | None,
    pages: list[PageText],
    images: dict[int, list[PlacedImage]],
    conversion: ConversionOptions,
    progress: Progress,
    probe: EngineProbe | None = None,
    declared_language: str | None = None,
) -> OcrOutcome:
    """OCR the pages that need it, reporting each as it finishes (OCR-R29). A page's
    ``fell_back`` is the reflow's own decision on the page as OCR left it.

    The OCR language follows OCR-R26, ``declared_language`` being the PDF's own.
    ``probe`` is what the run's preflight found out about the engine; without one, the
    engine is probed here, if any page needs OCR. When the engine or the OCR language's
    data is missing, those pages become page images with reason ``ocr_unavailable``
    (OCR-R24)."""
    options = conversion.ocr
    languages = ocr_languages(conversion, declared_language)
    scripts = language_scripts(languages)
    words = wordlist(conversion.language or declared_language or DEFAULT_LANGUAGE)
    # The text-layer quality check (OCR-R5 to OCR-R9), on every page with a text layer
    # that isn't OCR'd directly.
    layered = [p for p in pages if p.lines and not ocr_directly(p, images.get(p.page, []))]
    checks = check_layers(path, password, layered, images, scripts, words)
    rejected = {number: check.reason for number, check in checks.items() if check.reason}
    # Under ``always`` the layer's verdict only decides what an empty or failed OCR
    # result leaves (OCR-R10, OCR-R31): it routes nothing, so nothing is reported.
    issues = [] if options.mode == "always" else _rejections(rejected)
    if options.mode == "never":
        # OCR-R3: a rejected page, and a page that would be OCR'd directly, falls back.
        bad = {
            p.page
            for p in pages
            if p.page in rejected
            or (not _blank(p, images.get(p.page, [])) and ocr_directly(p, images.get(p.page, [])))
        }
        pages = [
            _fall_back(p, BAD_TEXT_LAYER, checks.get(p.page)) if p.page in bad else p for p in pages
        ]
        return OcrOutcome(pages, images, None, issues)
    routed = [
        (page, trigger)
        for page in pages
        if (trigger := route(page, images.get(page.page, []), options.mode, page.page in rejected))
        is not None
    ]
    if not routed:
        return OcrOutcome(pages, images, None, issues)
    if probe is None:
        probe = ocr_engine.probe_engine(options)
    engine = probe.engine
    missing = probe.missing(languages)
    if engine is None or missing:
        # OCR-R24: the pages that need OCR fall back; one warning says how to install.
        unrun = {page.page for page, _ in routed}
        pages = [
            _fall_back(p, OCR_UNAVAILABLE, checks.get(p.page)) if p.page in unrun else p
            for p in pages
        ]
        return OcrOutcome(pages, images, None, [*issues, unavailable(missing if engine else None)])
    engine_options = {
        key.removeprefix("tesseract."): value for key, value in options.engine_options.items()
    }
    replaced: dict[int, PageText] = {}
    kept_images = dict(images)
    failed: dict[str, list[int]] = {}
    # Asked once, before any page's budget starts.
    capabilities = engine.capabilities()
    osd = capabilities.osd
    document = pdfium.PdfDocument(path, password=password.reveal() if password else None)
    try:
        for done, (page, trigger) in enumerate(routed, start=1):
            image = render_grey(document, page.page, OCR_DPI)
            deadline = time.monotonic() + options.page_timeout
            recognition = ladder.recognise(
                engine, image, OCR_DPI, options, languages, engine_options, deadline, osd=osd
            )
            result = recognition.result
            read = page_text(page, result, OCR_DPI, recognition.frame)
            text: PageText | None = None
            if recognition.reason in (OCR_TIMEOUT, OCR_FAILED):
                log.warning("OCR on page %d of %s: %s", page.page, path, recognition.reason)
                failed.setdefault(recognition.reason, []).append(page.page)
            check = checks.get(page.page)
            if recognition.reason is None:
                text = read
            elif recognition.reason == OCR_LOW_CONFIDENCE and read is None:
                # Every attempt read nothing: the page keeps what it had (OCR-R17,
                # OCR-R31), unless its layer was rejected; then it is a page image with
                # no hidden text.
                if check is not None and check.reason is not None:
                    text = replace(page, lines=[], fallback=OCR_LOW_CONFIDENCE)
            else:
                # The page falls back, its hidden text the better of what OCR read and
                # its own text layer, never a garbled layer (OCR-R10).
                hidden = _hidden_text(page, read, check, scripts, words)
                text = replace(hidden, fallback=recognition.reason)
            if text is not None:
                replaced[page.page] = text
                if text.ocr:
                    # Only the scan the text was read from stops being a book image: the
                    # large image that routed the page, or one covering the whole page.
                    scan = LARGE_IMAGE if trigger == "no_text_layer" else FULL_PAGE
                    kept_images[page.page] = [
                        placed for placed in images.get(page.page, []) if share(placed, page) < scan
                    ]
            progress(
                "ocr",
                done,
                len(routed),
                page=page.page,
                trigger=trigger,
                confidence=round(result.page_confidence, 4),
                coverage=round(result.coverage, 4),
                attempts=len(result.attempts),
                fell_back=fallback_reason(text or page, conversion) is not None,
            )
    finally:
        document.close()
    summary = OcrSummary(
        engine=capabilities.name,
        engine_version=capabilities.version,
        languages=languages.split("+"),
        quality=options.quality,
    )
    pages = [replaced.get(page.page, page) for page in pages]
    issues.extend(
        Issue(IssueCode(reason), _FAILURE_MESSAGES[reason], pages=failed[reason])
        for reason in (OCR_TIMEOUT, OCR_FAILED)
        if reason in failed
    )
    return OcrOutcome(pages, {k: v for k, v in kept_images.items() if v}, summary, issues)


def unavailable(missing: list[str] | None) -> Issue:
    """The ``ocr_unavailable`` warning, with an install hint (OCR-R24): for Tesseract
    itself when ``missing`` is None, else for the language data in ``missing``."""
    if missing is None:
        message = "Pages needed OCR but Tesseract was not found; they were embedded as page images."
        hint = (
            "Install Tesseract: `brew install tesseract tesseract-lang` on macOS, "
            "`sudo apt install tesseract-ocr` on Debian or Ubuntu; or name the program "
            "with --tesseract or PDF2EPUB_TESSERACT."
        )
    else:
        codes = ", ".join(missing)
        packages = " ".join(f"tesseract-ocr-{code.replace('_', '-')}" for code in missing)
        message = (
            f"Pages needed OCR but Tesseract has no language data for {codes}; they were "
            "embedded as page images."
        )
        hint = (
            "Install the language data: `brew install tesseract-lang` on macOS, "
            f"`sudo apt install {packages}` on Debian or Ubuntu."
        )
    return Issue(IssueCode.OCR_UNAVAILABLE, message, hint=hint)


def _rejections(rejected: dict[int, str]) -> list[Issue]:
    """One ``text_layer_rejected`` issue per reason, its pages ascending (OCR-R9)."""
    return [
        Issue(
            IssueCode.TEXT_LAYER_REJECTED,
            _REJECTION_MESSAGES[reason],
            pages=sorted(page for page, why in rejected.items() if why == reason),
            reason=reason,
        )
        for reason in REASONS
        if reason in rejected.values()
    ]


def _fall_back(page: PageText, reason: str, check: LayerCheck | None) -> PageText:
    """``page`` as a page image for ``reason``, its text layer kept as hidden text unless
    it was rejected as garbled (OCR-R3, OCR-R10)."""
    garbled = check is not None and check.reason == GARBLED
    return replace(page, lines=[] if garbled else page.lines, fallback=reason)


def _hidden_text(
    page: PageText,
    read: PageText | None,
    check: LayerCheck | None,
    scripts: frozenset[str] | None,
    words: Collection[str] | None,
) -> PageText:
    """Whichever of what OCR read and the page's own text layer scores better on the
    text-layer signals (OCR-R7, OCR-R10): less garbage, then more plausible words; the
    layer when they score the same. A layer rejected as garbled is never used; with
    neither, the page has no text."""
    candidates = []
    if page.lines and (check is None or check.reason != GARBLED):
        candidates.append(page)
    if read is not None:
        candidates.append(read)
    if not candidates:
        return replace(page, lines=[])

    def score(candidate: PageText) -> tuple[float, float]:
        text = " ".join(line.text for line in candidate.lines)
        return garbage_ratio(text, scripts), -plausibility(text, words)[0]

    return min(candidates, key=score)


def page_text(
    page: PageText, result: OcrPageResult, dpi: int, frame: Frame | None = None
) -> PageText | None:
    """``page`` with the recognised lines as its text, or None if nothing was recognised.
    Word boxes are in pixels of the cleaned image at ``dpi``, turned upright as ``frame``
    says (by default, not turned). They are deliberately kept in that level frame, not
    turned back by the deskew angle: there each line is level and each column's edge is
    straight, which is what line heights (headings), gutters (columns) and reading order
    are measured on. Turning them back would tilt every line again. Lines are in reading
    order, in column order on a page set in columns."""
    # Words whose text normalisation leaves nothing (control characters, say) count as
    # not recognised, so such a result keeps the page's own text (OCR-R31).
    recognised = [
        OcrLine(kept, line.height)
        for line in result.lines
        if (kept := tuple(w for w in line.words if normalise(w.text).strip()))
    ]
    if not recognised:
        return None
    scale = _PDF_DPI / dpi
    if frame is not None and frame.rotation in (90, 270):
        # The page was turned a quarter: its lines run across what was its height.
        page = replace(page, width=page.height, height=page.width)
    heights = [line.height for line in recognised]
    body = median(heights)
    pieces = [_piece(line, scale, _size(line.height, body) * scale) for line in recognised]
    gutters = find_gutters(pieces)
    lines: list[tuple[Line, int | None]] = []
    for line, piece in zip(recognised, pieces, strict=True):
        for group in split(piece, gutters) if gutters else [list(range(len(line.words)))]:
            words = [line.words[index] for index in group]
            part = _piece(OcrLine(tuple(words), line.height), scale, piece.size)
            text = " ".join(normalise(w.text).strip() for w in words)
            if text:
                ocr_line = Line(text, part.x0, part.x1, part.top, part.bottom, piece.size)
                lines.append((ocr_line, column_of(part, gutters) if gutters else 0))
    return replace(page, lines=_reading_order(lines, gutters), columns=len(gutters) + 1, ocr=True)


def _size(height: float, body: float) -> float:
    """A line's size: the body lines' median height, unless it is clearly taller or
    shorter (RFL-R21)."""
    return body if abs(height - body) <= _SAME_HEIGHT * body else height


def _piece(line: OcrLine, scale: float, size: float) -> Piece:
    words = line.words
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
