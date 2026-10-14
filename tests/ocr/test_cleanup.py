"""Image cleanup before OCR (OCR-R18): the degraded scans are uprighted, deskewed and at
300 DPI when the engine gets them, and a page that falls back is embedded from its
un-cleaned render.

Skew and resolution are measured here independently of the pipeline: each text line,
smeared into one blob, is fitted with a minimum-area rectangle (its tilt), and the line
pitch in pixels against the novel's 14.5 pt leading gives the resolution
(``fixturegen/novel.py``). Upright means real Tesseract reads the page's own words.
"""

import io
import re
import time
import zipfile
from dataclasses import dataclass, field
from itertools import pairwise
from pathlib import Path
from statistics import median
from typing import Any

import cv2
import numpy as np
import pypdfium2 as pdfium
import pytest
from conftest import FIXTURES
from fake_engine import FakeEngine, install
from lxml import etree
from PIL import Image
from test_ladder import legible
from test_routing import XHTML, convert, page_contents

from pdf2epub import OcrOptions
from pdf2epub.ocr.engine import (
    Capabilities,
    OcrEngine,
    OcrPageResult,
    OcrRequest,
    load_engine,
)
from pdf2epub.ocr.ladder import recognise

SCANNED = FIXTURES / "scanned"
LEADING = 14.5  # points between the novel's body lines
DPI = 300


@dataclass
class Recording:
    """Real Tesseract, recording each request it gets."""

    engine: Any
    requests: list[OcrRequest] = field(default_factory=list)

    def capabilities(self) -> Capabilities:
        result: Capabilities = self.engine.capabilities()
        return result

    def recognise(self, request: OcrRequest) -> OcrPageResult:
        self.requests.append(request)
        result: OcrPageResult = self.engine.recognise(request)
        return result

    def orientation(self, image: Image.Image, dpi: int, deadline: float) -> int:
        turn: int = self.engine.orientation(image, dpi, deadline)
        return turn


def render(pdf: Path, page: int) -> Image.Image:
    """Page ``page`` (1-based) of ``pdf`` as a greyscale image at 300 DPI."""
    document = pdfium.PdfDocument(pdf)
    try:
        image: Image.Image = (
            document[page - 1].render(scale=DPI / 72, grayscale=True).to_pil().convert("L")
        )
        return image
    finally:
        document.close()


def text_lines(image: Image.Image) -> list[tuple[float, float, float]]:
    """Each body text line's (tilt in degrees, centre y, length), from the image's ink
    smeared sideways into one blob per line."""
    grey = np.asarray(image.convert("L"), dtype=np.uint8)
    ink = (grey < 128).astype(np.uint8)
    smeared = cv2.dilate(ink, np.ones((3, 25), np.uint8))
    count, labels, stats, _ = cv2.connectedComponentsWithStats(smeared, connectivity=8)
    lines = []
    for label in range(1, count):
        if stats[label][cv2.CC_STAT_WIDTH] < grey.shape[1] / 3:
            continue  # not a full body line: a title, a folio, a short last line
        ys, xs = np.nonzero(labels == label)
        (_, cy), (w, h), angle = cv2.minAreaRect(np.column_stack([xs, ys]).astype(np.float32))
        # The rectangle's angle is that of one of its sides: the tilt from level is the
        # smaller turn to either axis.
        folded = float(angle) % 90
        lines.append((min(folded, 90 - folded), float(cy), float(max(w, h))))
    return lines


def tilt(image: Image.Image) -> float:
    """The median tilt of the page's long text lines, in degrees."""
    lines = text_lines(image)
    assert len(lines) >= 10, "too few text lines to measure"
    return float(median(abs(angle) for angle, _, _ in lines))


def resolution(image: Image.Image) -> float:
    """Pixels per inch, from the median pitch between consecutive body lines."""
    centres = sorted(cy for _, cy, _ in text_lines(image))
    pitch = median(b - a for a, b in pairwise(centres))
    return float(pitch / LEADING * 72)


def words(text: str) -> list[str]:
    return re.findall(r"[A-Za-z]+", re.sub(r"-\s*\n\s*", "", text))


@pytest.mark.tesseract
@pytest.mark.ac("OCR-AC18")
@pytest.mark.parametrize("variant", ["novel-skew", "novel-rotated", "novel-150dpi"])
def test_the_engine_gets_degraded_pages_upright_level_and_at_300_dpi(variant: str) -> None:
    tesseract = load_engine(OcrOptions())
    assert tesseract is not None
    engine = Recording(tesseract)
    page = render(SCANNED / f"{variant}.pdf", 2)

    deadline = time.monotonic() + 170
    recognition = recognise(engine, page, DPI, OcrOptions(), "eng", {}, deadline, osd=True)

    assert recognition.reason is None
    for request in engine.requests:
        width, height = request.image.size
        assert height > width, "the page is not upright"
        assert tilt(request.image) < 0.5
        assert resolution(request.image) == pytest.approx(300, abs=10)
    # Tesseract read the page's own words, so it was the right way up.
    read = [w.text for w in recognition.result.words]
    truth = set(words((SCANNED / f"{variant}.txt").read_text(encoding="utf-8")))
    assert sum(re.sub(r"\W", "", w) in truth for w in read) > 0.9 * len(read)


def test_the_measurements_see_the_degradation() -> None:
    # The fixtures really are degraded as measured: without cleanup, the checks above fail.
    assert tilt(render(SCANNED / "novel-skew.pdf", 2)) == pytest.approx(2.0, abs=0.3)
    assert tilt(render(SCANNED / "novel-clean.pdf", 2)) < 0.2
    width, height = render(SCANNED / "novel-rotated.pdf", 2).size
    assert width > height
    low = Image.open(io.BytesIO(_embedded_scan(SCANNED / "novel-150dpi.pdf", 2)))
    assert resolution(low) == pytest.approx(150, abs=5)


def _embedded_scan(pdf: Path, page: int) -> bytes:
    """The scan image on page ``page`` of ``pdf``, as PNG."""
    document = pdfium.PdfDocument(pdf)
    try:
        [image] = list(document[page - 1].get_objects())
        assert isinstance(image, pdfium.PdfImage)
        buffer = io.BytesIO()
        image.get_bitmap().to_pil().save(buffer, format="PNG")
        return buffer.getvalue()
    finally:
        document.close()


@pytest.mark.ac("OCR-AC18")
def test_a_fallback_page_is_the_uncleaned_render(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # No attempt is accepted (``legible`` reads two faint words), so every page falls back.
    engine: OcrEngine = install(monkeypatch, FakeEngine(legible))

    report, _ = convert([(SCANNED / "novel-skew.pdf", "scan.pdf")], tmp_path)

    [result] = report.conversions
    assert result.output is not None
    assert isinstance(engine, FakeEngine)
    # The engine got the page deskewed...
    assert tilt(engine.requests[4].image) < 0.5  # page 2's first attempt
    # ...but the page image in the book is the page as scanned: still tilted 2 degrees.
    [figure] = page_contents(Path(result.output))[2]
    [img] = figure.iter(f"{XHTML}img")
    with zipfile.ZipFile(result.output) as archive:
        embedded = Image.open(io.BytesIO(archive.read(f"OEBPS/{img.get('src')}")))
        embedded.load()
    assert tilt(embedded) == pytest.approx(2.0, abs=0.3)
    assert etree.QName(figure).localname == "figure"
