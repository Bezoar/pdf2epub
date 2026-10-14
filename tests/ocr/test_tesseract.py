"""The Tesseract adapter: real Tesseract at the ``OcrEngine`` seam, and fake ``tesseract``
programs through ``plan_batch`` / ``run_batch`` (OCR-R11 to OCR-R15, OCR-R22, OCR-R23,
API-R22).

Tests marked ``tesseract`` need the real program. The others put a fake ``tesseract``
(``fake_tesseract.py``) in ``OcrOptions.tesseract_path``, so they run everywhere.
Conversions run in-process, so the adapter's own subprocess is the one under test.
"""

import json
import re
import shutil
import time
from pathlib import Path
from typing import Any

import pypdfium2 as pdfium
import pytest
from conftest import FIXTURES, RecordingSink
from fake_tesseract import EXIT_1, SLEEP_FOREVER, alive, fake_tesseract, record, started
from test_routing import page_contents

from pdf2epub import (
    BatchOptions,
    ConversionOptions,
    DiscoveryOptions,
    InputSpec,
    OcrOptions,
    Outcome,
    plan_batch,
    run_batch,
)
from pdf2epub.ocr.engine import OcrRequest, load_engine
from pdf2epub.ocr.pages import attempt
from pdf2epub.results import BatchReport

SCANNED = FIXTURES / "scanned"
OCR_DPI = 300


class TimedSink(RecordingSink):
    """A recording sink that also notes when (``time.time()``) each event arrived."""

    def __init__(self) -> None:
        super().__init__()
        self.times: list[float] = []

    def __call__(self, event: dict[str, Any]) -> None:
        super().__call__(event)
        self.times.append(time.time())


def convert(
    source: Path, folder: Path, ocr: OcrOptions, sink: RecordingSink | None = None
) -> tuple[BatchReport, RecordingSink]:
    pdf = folder / "scan.pdf"
    shutil.copyfile(source, pdf)
    sink = sink if sink is not None else RecordingSink()
    plan = plan_batch([InputSpec(pdf)], DiscoveryOptions())
    report = run_batch(plan, BatchOptions(isolation="inprocess"), ConversionOptions(ocr=ocr), sink)
    return report, sink


def ocr_events(sink: RecordingSink) -> list[dict[str, Any]]:
    return [e for e in sink.of_type("progress") if e["stage"] == "ocr"]


def issues_of(report: BatchReport) -> list[tuple[str, list[int], str | None]]:
    return [
        (str(issue.code), list(issue.pages), issue.reason) for issue in report.conversions[0].issues
    ]


def render(pdf: Path, page: int) -> Any:
    """Page ``page`` (1-based) of ``pdf`` as a greyscale image at 300 DPI."""
    document = pdfium.PdfDocument(pdf)
    try:
        return document[page - 1].render(scale=OCR_DPI / 72, grayscale=True).to_pil().convert("L")
    finally:
        document.close()


def words(text: str) -> list[str]:
    """The words of ``text``, with words hyphenated across lines joined again."""
    return re.findall(r"[A-Za-z]+", re.sub(r"-\s*\n\s*", "", text))


def includes(read: list[str], expected: list[str]) -> bool:
    """Whether ``expected`` is a run of consecutive words in ``read``."""
    return any(read[i : i + len(expected)] == expected for i in range(len(read)))


# --- Real Tesseract ---------------------------------------------------------------------


@pytest.mark.tesseract
@pytest.mark.ac("OCR-AC11")
def test_tesseract_returns_lines_of_words_with_boxes_and_normalised_confidence() -> None:
    engine = load_engine(OcrOptions())
    assert engine is not None
    image = render(SCANNED / "novel-clean.pdf", 1)
    request = OcrRequest(image, OCR_DPI, "eng", "PAGE", time.monotonic() + 120)

    result = attempt(engine, request)

    assert result.lines
    width, height = image.size
    for line in result.lines:
        assert line.words
        assert line.height > 0
        for word in line.words:
            assert 0 <= word.x0 < word.x1 <= width
            assert 0 <= word.top < word.bottom <= height
            assert 0.0 <= word.confidence <= 1.0
            assert word.confidence == word.raw_confidence / 100
    found = result.words
    weighted = sum(w.confidence * len(w.text) for w in found) / sum(len(w.text) for w in found)
    assert result.page_confidence == pytest.approx(weighted)
    assert len(result.attempts) == 1
    # What Tesseract read is the scanned page's text, in reading order (the ground truth
    # is the text the scan was rendered from).
    truth = words((SCANNED / "novel-clean.txt").read_text(encoding="utf-8"))
    read = words("\n".join(" ".join(w.text for w in line.words) for line in result.lines))
    assert includes(read, truth[:20]), read[:30]
    capabilities = engine.capabilities()
    assert capabilities.name == "tesseract"
    assert re.fullmatch(r"\d+\.\d+(\.\d+)?", capabilities.version)
    assert capabilities.licence == "Apache-2.0"
    assert capabilities.osd is True


@pytest.mark.tesseract
@pytest.mark.ac("API-AC12")
def test_an_image_only_scan_emits_one_ocr_event_per_page(tmp_path: Path) -> None:
    report, sink = convert(SCANNED / "two-pages.pdf", tmp_path, OcrOptions(mode="auto"))

    assert report.conversions[0].outcome is Outcome.CONVERTED
    events = ocr_events(sink)
    assert [e["page"] for e in events] == [1, 2]
    for event in events:
        assert event["trigger"] == "no_text_layer"
        assert 0.0 <= event["confidence"] <= 1.0
        assert 0.0 <= event["coverage"] <= 1.0
        assert event["attempts"] >= 1
        assert isinstance(event["fell_back"], bool)
    [finished] = sink.of_type("conversion_finished")
    assert finished["ocr"]["engine"] == "tesseract"
    # Tesseract read the pages: the words the scan was rendered from are in the book.
    truth = words((SCANNED / "two-pages.txt").read_text(encoding="utf-8"))
    contents = page_contents(Path(str(report.conversions[0].output)))
    read = words(" ".join("".join(map(str, e.itertext())) for e in contents[1]))
    assert includes(read, truth[:10]), read[:20]


# --- Fake tesseract programs -----------------------------------------------------------


@pytest.mark.ac("OCR-AC12")
def test_a_hung_tesseract_is_killed_at_the_page_timeout(tmp_path: Path) -> None:
    starts = tmp_path / "starts.jsonl"
    program = fake_tesseract(tmp_path / "bin", started(starts, SLEEP_FOREVER))
    sink = TimedSink()

    report, _ = convert(
        SCANNED / "two-pages.pdf",
        tmp_path,
        OcrOptions(page_timeout=2, tesseract_path=program),
        sink,
    )

    result = report.conversions[0]
    assert result.outcome is Outcome.CONVERTED
    # Only the recognition calls (image on stdin), not the preflight's probe (OCR-R24).
    logged = [json.loads(line) for line in starts.read_text(encoding="utf-8").splitlines()]
    runs = [run for run in logged if "stdin" in run["argv"]]
    assert len(runs) == 2
    events = [(e, t) for e, t in zip(sink.events, sink.times, strict=True) if e in ocr_events(sink)]
    for run, (event, reported) in zip(runs, events, strict=True):
        assert reported - run["time"] < 2 + 1.5, "the hung page was not stopped at its budget"
        assert not alive(run["pid"]), "a tesseract process outlived its page"
        assert event["fell_back"] is True
    assert ("page_fallback", [1, 2], "ocr_timeout") in issues_of(report)
    assert ("ocr_timeout", [1, 2], None) in issues_of(report)
    images = page_contents(Path(str(result.output)))
    for page in (1, 2):
        assert [e.get("class") for e in images[page]] == ["page-image"]


@pytest.mark.ac("OCR-AC13")
def test_tesseract_runs_with_one_thread_and_no_password_variable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = tmp_path / "calls.jsonl"
    program = fake_tesseract(tmp_path / "bin", record(calls))
    monkeypatch.setenv("PDF2EPUB_PASSWORD", "hunter2")
    monkeypatch.setenv("OMP_THREAD_LIMIT", "8")

    report, _ = convert(SCANNED / "two-pages.pdf", tmp_path, OcrOptions(tesseract_path=program))

    assert report.conversions[0].outcome is Outcome.CONVERTED
    runs = [json.loads(line) for line in calls.read_text(encoding="utf-8").splitlines()]
    assert len(runs) == 2
    for run in runs:
        assert run["env"]["OMP_THREAD_LIMIT"] == "1"
        assert "PDF2EPUB_PASSWORD" not in run["env"]
        assert not any("hunter2" in value for value in run["env"].values())


@pytest.mark.ac("OCR-AC14")
@pytest.mark.parametrize(
    "body", [EXIT_1, "print('not TSV')"], ids=["exit-status-1", "unreadable-output"]
)
def test_a_crashing_tesseract_costs_the_pages_not_the_conversion(tmp_path: Path, body: str) -> None:
    program = fake_tesseract(tmp_path / "bin", body)

    report, sink = convert(SCANNED / "two-pages.pdf", tmp_path, OcrOptions(tesseract_path=program))

    result = report.conversions[0]
    assert result.outcome is Outcome.CONVERTED
    issues = issues_of(report)
    assert ("page_fallback", [1, 2], "ocr_failed") in issues
    assert [i for i in issues if i[0] == "ocr_failed"] == [("ocr_failed", [1, 2], None)]
    assert [e["fell_back"] for e in ocr_events(sink)] == [True, True]
    images = page_contents(Path(str(result.output)))
    for page in (1, 2):
        assert [e.get("class") for e in images[page]] == ["page-image"]
