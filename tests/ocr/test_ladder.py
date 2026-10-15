"""The acceptance test and the retry ladder, at the ``OcrEngine`` seam with a fake engine
(OCR-R16, OCR-R19, OCR-R20, OCR-R21, OCR-R27).

``recognise`` runs one page through cleanup and the ladder. The page is a synthetic image
with known ink: lines of glyph-sized blocks, the two halves of each line mirror images of
each other about the page's vertical centre line. The fake engine "reads" words whose
boxes it places from the image it is sent, so its scripted coverage holds whatever
cleanup cropped.
"""

import re
import time
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

import pytest
from fake_engine import FakeEngine, install
from PIL import Image, ImageDraw
from test_routing import (
    BORN_DIGITAL,
    SCANNED,
    XHTML,
    convert,
    ocr_events,
    page_contents,
    squash,
    text_of,
)

from pdf2epub import OcrOptions, Outcome
from pdf2epub.ocr.engine import OcrLine, OcrPageResult, OcrRequest, Word
from pdf2epub.ocr.ladder import P_MIN, Recognition, recognise

DPI = 300


LINES, GLYPHS = 30, 40
"""The page's text: 30 lines of 40 glyph-sized blocks."""
LINE_TOP, LINE_STEP, GLYPH_HEIGHT = 600, 60, 30
GLYPH_LEFT, GLYPH_STEP, GLYPH_WIDTH = 305, 30, 20
LINE_MARGIN = 5
"""How far a word's box reaches above and below its line's glyphs."""


def page() -> Image.Image:
    """A 6 x 9 in white page at 300 DPI whose only ink is 30 lines of 40 black 20 x 30 px
    blocks, the size of 10 pt letters, 10 px apart: 20 blocks of each line lie left of the
    page's vertical centre line and 20, their mirror images, right of it."""
    image = Image.new("L", (1800, 2700), 255)
    draw = ImageDraw.Draw(image)
    for line in range(LINES):
        top = LINE_TOP + line * LINE_STEP
        for glyph in range(GLYPHS):
            left = GLYPH_LEFT + glyph * GLYPH_STEP
            draw.rectangle((left, top, left + GLYPH_WIDTH - 1, top + GLYPH_HEIGHT - 1), fill=0)
    return image


def boxes(request: OcrRequest, share: float, confidence: float) -> OcrPageResult:
    """One word per line, its box the line's height (and a little more) and spanning the
    left ``share`` of the request image: with ``share`` 0.5 the words hold exactly the
    left half of the ink; with 1, all of it."""
    width = request.image.size[0]
    lines = []
    for line in range(LINES):
        top = LINE_TOP + line * LINE_STEP - LINE_MARGIN
        bottom = top + GLYPH_HEIGHT + 2 * LINE_MARGIN
        word = Word("word", 0, top, width * share, bottom, confidence, confidence * 100)
        lines.append(OcrLine((word,), bottom - top))
    return OcrPageResult(lines=tuple(lines))


def run(engine: FakeEngine, image: Image.Image | None = None, **options: object) -> Recognition:
    return recognise(
        engine,
        page() if image is None else image,
        DPI,
        OcrOptions(**options),  # type: ignore[arg-type]
        "eng",
        {},
        time.monotonic() + 60,
        osd=False,
    )


@pytest.mark.ac("OCR-AC15")
def test_coverage_is_the_share_of_ink_inside_word_boxes() -> None:
    engine = FakeEngine(lambda call, request: boxes(request, 0.5, 0.95))

    recognition = run(engine, quality="fast")

    assert recognition.result.coverage == pytest.approx(0.5, abs=0.02)
    assert recognition.result.page_confidence == pytest.approx(0.95)
    assert P_MIN < 0.95
    # Confident, but half the ink is outside every word: not accepted.
    assert recognition.reason == "ocr_low_confidence"


def illustrated_page() -> Image.Image:
    """``page()`` with a black 600 x 400 px picture plate above its text, as a book's
    illustration: ink no word box holds that is not text."""
    image = page()
    ImageDraw.Draw(image).rectangle((600, 150, 1199, 549), fill=0)
    return image


def low_boxes(request: OcrRequest) -> OcrPageResult:
    """``boxes(request, 1.0, 0.95)`` with every box moved down by half a line's glyph
    height: each glyph's top half lies above every box."""
    full = boxes(request, 1.0, 0.95)
    shift = GLYPH_HEIGHT // 2
    lines = [
        OcrLine(
            tuple(replace(w, top=w.top + shift, bottom=w.bottom + shift) for w in line.words),
            line.height,
        )
        for line in full.lines
    ]
    return OcrPageResult(lines=tuple(lines))


def missing_lines(count: int) -> Callable[[int, OcrRequest], OcrPageResult]:
    """Words for every line but the last ``count``."""

    def read(call: int, request: OcrRequest) -> OcrPageResult:
        full = boxes(request, 1.0, 0.95)
        return OcrPageResult(lines=full.lines[: LINES - count])

    return read


# One glyph is 20 x 30 px of ink and a unit (OCR-R16) is a square one box height (40 px)
# across, so a glyph is 600 / 1600 = 0.375 units and a line of 40 glyphs 15 units.
UNITS_PER_LINE = GLYPHS * GLYPH_WIDTH * GLYPH_HEIGHT / (GLYPH_HEIGHT + 2 * LINE_MARGIN) ** 2


@pytest.mark.ac("OCR-AC26")
def test_a_picture_and_boxes_set_low_on_their_glyphs_leave_coverage_full() -> None:
    recognition = run(FakeEngine(lambda call, request: low_boxes(request)), illustrated_page())

    assert recognition.result.coverage == 1.0
    assert recognition.reason is None


@pytest.mark.ac("OCR-AC26")
def test_text_missed_under_the_allowance_leaves_coverage_full() -> None:
    # 5 lines missed: 75 units, under the 80-unit allowance.
    assert 5 * UNITS_PER_LINE < 80 <= 6 * UNITS_PER_LINE

    recognition = run(FakeEngine(missing_lines(5)), quality="fast")

    assert recognition.result.coverage == 1.0
    assert recognition.reason is None


@pytest.mark.ac("OCR-AC26")
def test_text_missed_over_the_allowance_makes_coverage_the_share() -> None:
    # 7 lines of 30 missed: 105 units, so coverage is the share of glyphs boxed, 23 / 30,
    # below C_MIN: the confident attempt is not accepted.
    recognition = run(FakeEngine(missing_lines(7)), quality="fast")

    assert recognition.result.coverage == pytest.approx(23 / 30, abs=0.001)
    assert recognition.reason == "ocr_low_confidence"


def dark_plate_page() -> Image.Image:
    """Dark print beside a dark picture: a black 1700 x 1600 px plate, more than half the
    page, above 14 lines of ``page()``'s glyph blocks."""
    image = Image.new("L", (1800, 2700), 255)
    draw = ImageDraw.Draw(image)
    draw.rectangle((50, 100, 1749, 1699), fill=0)
    for line in range(14):
        top = 1800 + line * LINE_STEP
        for glyph in range(GLYPHS):
            left = GLYPH_LEFT + glyph * GLYPH_STEP
            draw.rectangle((left, top, left + GLYPH_WIDTH - 1, top + GLYPH_HEIGHT - 1), fill=0)
    return image


def test_a_page_mostly_dark_from_a_picture_is_not_read_as_light_print() -> None:
    # Words for the first 7 of the 14 lines: 105 units of the print missed, so coverage is
    # the share, 1/2. Read inverted, the page would have no text-like ink to miss.
    assert 7 * UNITS_PER_LINE >= 80

    def half(call: int, request: OcrRequest) -> OcrPageResult:
        words = []
        for line in range(7):
            top = 1800 + line * LINE_STEP - LINE_MARGIN
            bottom = top + GLYPH_HEIGHT + 2 * LINE_MARGIN
            words.append(Word("word", 0, top, request.image.size[0], bottom, 0.95, 95))
        return OcrPageResult(lines=tuple(OcrLine((w,), w.bottom - w.top) for w in words))

    recognition = run(FakeEngine(half), dark_plate_page(), quality="fast")

    assert recognition.result.coverage == pytest.approx(0.5, abs=0.001)
    assert recognition.reason == "ocr_low_confidence"


def test_a_word_box_off_the_image_covers_no_ink() -> None:
    # A box wholly above and left of the image must not wrap round to cover its far side.
    def half_and_off(call: int, request: OcrRequest) -> OcrPageResult:
        result = boxes(request, 0.5, 0.95)
        off = Word("off", -50, -50, -10, -10, 0.95, 95)
        return OcrPageResult(lines=(*result.lines, OcrLine((off,), 40)))

    recognition = run(FakeEngine(half_and_off), quality="fast")

    assert recognition.result.coverage == pytest.approx(0.5, abs=0.02)


def low_coverage_then_block(call: int, request: OcrRequest) -> OcrPageResult:
    """Low coverage unless asked for a ``BLOCK`` layout; later attempts slightly better
    still, so ``best`` has a clear winner."""
    if request.layout_hint == "BLOCK":
        return boxes(request, 1.0, 0.90)
    return boxes(request, 0.5, 0.95 if call == 0 else 0.96)


@pytest.mark.ac("OCR-AC16")
def test_balanced_stops_at_the_first_accepted_attempt() -> None:
    engine = FakeEngine(low_coverage_then_block)

    recognition = run(engine)

    assert [r.layout_hint for r in engine.requests] == ["PAGE", "BLOCK"]
    assert recognition.reason is None
    assert [a.variant for a in recognition.result.attempts] == ["baseline", "block"]
    assert recognition.result.coverage == pytest.approx(1.0)
    assert recognition.result.page_confidence == pytest.approx(0.90)


@pytest.mark.ac("OCR-AC16")
def test_fast_runs_the_baseline_only() -> None:
    engine = FakeEngine(low_coverage_then_block)

    recognition = run(engine, quality="fast")

    assert len(engine.requests) == 1
    assert len(recognition.result.attempts) == 1
    assert recognition.reason == "ocr_low_confidence"


@pytest.mark.ac("OCR-AC16")
def test_best_runs_all_four_attempts_and_keeps_the_highest_coverage_then_confidence() -> None:
    def script(call: int, request: OcrRequest) -> OcrPageResult:
        # Full coverage on attempts 2 and 4; attempt 4 the more confident.
        return boxes(request, 1.0 if call in (1, 3) else 0.5, [0.99, 0.80, 0.99, 0.85][call])

    engine = FakeEngine(script)

    recognition = run(engine, quality="best")

    assert len(engine.requests) == 4
    assert [a.variant for a in recognition.result.attempts] == [
        "baseline",
        "block",
        "sauvola",
        "sauvola+denoise",
    ]
    assert recognition.reason is None
    assert recognition.result.coverage == pytest.approx(1.0)
    assert recognition.result.page_confidence == pytest.approx(0.85)


@pytest.mark.ac("OCR-AC17")
@pytest.mark.parametrize(("minimum", "reason"), [(0.75, None), (0.90, "ocr_low_confidence")])
def test_min_confidence_replaces_the_acceptance_threshold(
    minimum: float, reason: str | None
) -> None:
    engine = FakeEngine(lambda call, request: boxes(request, 1.0, 0.80))

    recognition = run(engine, min_confidence=minimum)

    assert recognition.reason == reason
    if reason is None:
        # The baseline attempt is accepted: nothing more runs.
        assert len(engine.requests) == 1
    else:
        # Full coverage skips the BLOCK step; both Sauvola steps try for confidence.
        assert [a.variant for a in recognition.result.attempts] == [
            "baseline",
            "sauvola",
            "sauvola+denoise",
        ]


# --- Through the API: a page no attempt is accepted on ----------------------------------


def garbled(call: int, request: OcrRequest) -> OcrPageResult:
    """Every attempt: one small word of Private Use Area and replacement characters, with
    low confidence, far from most of the ink."""
    word = Word("�", 10, 10, 60, 40, 0.30, 30)
    return OcrPageResult(lines=(OcrLine((word,), 30),))


def legible(call: int, request: OcrRequest) -> OcrPageResult:
    """Every attempt: two plain words with low confidence, far from most of the ink."""
    words = (Word("Faint", 10, 10, 60, 40, 0.30, 30), Word("words", 70, 10, 130, 40, 0.30, 30))
    return OcrPageResult(lines=(OcrLine(words, 30),))


@pytest.mark.ac("OCR-AC10")
def test_a_page_no_attempt_is_accepted_on_falls_back_with_the_cleaner_hidden_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The born-digital two-page book's text layer is clean; every OCR attempt reads
    # garbage. (Rejecting a layer under ``auto`` is the text-layer quality check's; here
    # ``always`` sends the layer's pages to OCR.)
    source = BORN_DIGITAL / "two-pages.pdf"
    engine = install(monkeypatch, FakeEngine(garbled))

    report, sink = convert([(source, "book.pdf")], tmp_path, "always")

    [result] = report.conversions
    assert result.outcome is Outcome.CONVERTED
    fallbacks = {i.reason: i.pages for i in result.issues if str(i.code) == "page_fallback"}
    assert fallbacks == {"ocr_low_confidence": [1, 2]}
    # Low coverage, then low confidence: all four ladder steps run on each page.
    assert len(engine.requests) == 8
    assert [(e["attempts"], e["fell_back"]) for e in ocr_events(sink)] == [(4, True)] * 2
    assert result.output is not None
    pages = page_contents(Path(result.output))
    paragraphs = source.with_suffix(".txt").read_text(encoding="utf-8").split("\n\n")
    for number, paragraph in enumerate(paragraphs, start=1):
        [figure] = pages[number]
        assert figure.tag == f"{XHTML}figure"
        # The hidden text is the layer: it has no garbage; OCR's text is all garbage.
        assert squash(paragraph) in text_of([figure])
        assert not re.search("[-�]", text_of([figure]))


@pytest.mark.ac("OCR-AC10")
def test_a_scan_no_attempt_is_accepted_on_keeps_the_best_attempt_as_hidden_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install(monkeypatch, FakeEngine(legible))

    report, sink = convert([(SCANNED / "two-pages.pdf", "scan.pdf")], tmp_path)

    [result] = report.conversions
    fallbacks = {i.reason: i.pages for i in result.issues if str(i.code) == "page_fallback"}
    assert fallbacks == {"ocr_low_confidence": [1, 2]}
    assert [e["attempts"] for e in ocr_events(sink)] == [4, 4]
    assert result.output is not None
    pages = page_contents(Path(result.output))
    for number in (1, 2):
        [figure] = pages[number]
        assert text_of([figure]) == "Faint words"
