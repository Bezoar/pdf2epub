"""OCR page routing through the ``OcrEngine`` protocol, with a fake engine (OCR-R1,
OCR-R2, OCR-R4, OCR-R17, OCR-R29, OCR-R30, OCR-R31, RFL-R11, RFL-R21).

Conversions run in-process through ``plan_batch`` / ``run_batch``; the fake engine
(``fake_engine.py``) stands in for Tesseract. Which pages are blank, scanned or typeset
comes from the fixtures' generators (``fixturegen/blank.py``, ``fixturegen/scans.py``);
the words a scripted engine "reads" off a scan come from the born-digital fixture the scan
was rendered from.
"""

import re
import shutil
import zipfile
from pathlib import Path
from typing import Any

import pypdfium2 as pdfium
import pytest
from conftest import FIXTURES, RecordingSink
from fake_engine import CONFIDENCE, FakeEngine, install, no_words, words_of
from lxml import etree

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
from pdf2epub.ocr.engine import OcrLine, OcrPageResult, OcrRequest, Word
from pdf2epub.results import BatchReport

BORN_DIGITAL = FIXTURES / "born-digital"
SCANNED = FIXTURES / "scanned"
XHTML = "{http://www.w3.org/1999/xhtml}"
EPUB_TYPE = "{http://www.idpf.org/2007/ops}type"
OPF_NS = {"opf": "http://www.idpf.org/2007/opf"}
MARKS = ("em", "i", "strong", "b")
OCR_ISSUES = {"ocr_unavailable", "ocr_timeout", "ocr_failed", "text_layer_rejected"}


def convert(
    sources: list[tuple[Path, str]],
    folder: Path,
    mode: str = "auto",
) -> tuple[BatchReport, RecordingSink]:
    """Convert copies of ``sources`` (each copied under the given name) in one batch, in
    OCR ``mode``."""
    inputs = []
    for source, name in sources:
        shutil.copyfile(source, folder / name)
        inputs.append(InputSpec(folder / name))
    sink = RecordingSink()
    plan = plan_batch(inputs, DiscoveryOptions())
    options = ConversionOptions(ocr=OcrOptions(mode=mode))  # type: ignore[arg-type]
    report = run_batch(plan, BatchOptions(isolation="inprocess"), options, sink)
    return report, sink


def ocr_events(sink: RecordingSink, id_: int = 0) -> list[dict[str, Any]]:
    return [e for e in sink.of_type("progress") if e["stage"] == "ocr" and e["id"] == id_]


def issue_codes(report: BatchReport, index: int = 0) -> list[str]:
    return [str(issue.code) for issue in report.conversions[index].issues]


def one_line(call: int, request: OcrRequest) -> OcrPageResult:
    """One recognised line in the middle of the page."""
    word = Word("Recognised", 300, 1300, 900, 1360, CONFIDENCE, 95)
    return OcrPageResult(lines=(OcrLine((word,), 60),))


def chapters(epub: Path) -> list[etree._Element]:
    """The body of every spine document, in order."""
    bodies = []
    with zipfile.ZipFile(epub) as archive:
        opf = etree.fromstring(archive.read("OEBPS/content.opf"))
        items = {i.get("id"): i.get("href") for i in opf.findall("opf:manifest/opf:item", OPF_NS)}
        for ref in opf.findall("opf:spine/opf:itemref", OPF_NS):
            root = etree.fromstring(archive.read(f"OEBPS/{items[ref.get('idref')]}"))
            body = root.find(f"{XHTML}body")
            assert body is not None
            bodies.append(body)
    return bodies


def squash(text: str) -> str:
    return " ".join(text.split())


def page_contents(epub: Path) -> dict[int, list[etree._Element]]:
    """The elements after each page-break marker, by page number."""
    pages: dict[int, list[etree._Element]] = {}
    current: list[etree._Element] | None = None
    for body in chapters(epub):
        for element in body.iter(f"{XHTML}p", f"{XHTML}figure", f"{XHTML}span"):
            if element.get(EPUB_TYPE) == "pagebreak":
                current = pages.setdefault(int(str(element.get("id")).removeprefix("page-")), [])
            elif current is not None and element.tag != f"{XHTML}span":
                current.append(element)
    return pages


def text_of(elements: list[etree._Element]) -> str:
    return squash(" ".join("".join(map(str, e.itertext())) for e in elements))


# --- Routing ----------------------------------------------------------------------------


@pytest.mark.ac("OCR-AC1")
def test_image_only_pages_are_ocred_with_trigger_no_text_layer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = install(monkeypatch, FakeEngine(one_line))

    report, sink = convert([(SCANNED / "image-only.pdf", "scan.pdf")], tmp_path)

    assert report.conversions[0].outcome is Outcome.CONVERTED
    assert len(engine.requests) == 3
    events = ocr_events(sink)
    assert [(e["page"], e["trigger"]) for e in events] == [
        (1, "no_text_layer"),
        (2, "no_text_layer"),
        (3, "no_text_layer"),
    ]
    assert [(e["done"], e["of"]) for e in events] == [(1, 3), (2, 3), (3, 3)]
    assert "text_layer_rejected" not in issue_codes(report)
    # The engine gets each page at 300 DPI (6 x 9 in pages).
    assert {(r.dpi, r.image.size, r.layout_hint) for r in engine.requests} == {
        (300, (1800, 2700), "PAGE")
    }


@pytest.mark.ac("OCR-AC2")
def test_a_blank_page_is_never_ocred_and_raises_no_issue(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = install(monkeypatch, FakeEngine(one_line))

    report, sink = convert([(BORN_DIGITAL / "blank-page.pdf", "book.pdf")], tmp_path)

    assert report.conversions[0].outcome is Outcome.CONVERTED
    assert engine.requests == []
    assert ocr_events(sink) == []
    assert not OCR_ISSUES & set(issue_codes(report))
    assert "page_fallback" not in issue_codes(report)


@pytest.mark.ac("OCR-AC2")
@pytest.mark.ac("OCR-AC8")
def test_always_ocrs_every_page_but_the_blank_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = install(monkeypatch, FakeEngine(one_line))

    report, sink = convert([(BORN_DIGITAL / "blank-page.pdf", "book.pdf")], tmp_path, "always")

    assert len(engine.requests) == 2
    assert [(e["page"], e["trigger"]) for e in ocr_events(sink)] == [(1, "forced"), (3, "forced")]
    assert not OCR_ISSUES & set(issue_codes(report))


@pytest.mark.ac("OCR-AC8")
def test_always_ocrs_a_trusted_text_layer_with_trigger_forced(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = BORN_DIGITAL / "two-pages.pdf"
    engine = install(monkeypatch, FakeEngine(words_of(source, 300)))

    # Under auto the text layer is trusted: no OCR at all.
    report, sink = convert([(source, "auto.pdf")], tmp_path)
    assert engine.requests == []
    assert ocr_events(sink) == []
    assert report.conversions[0].ocr is None

    report, sink = convert([(source, "always.pdf")], tmp_path, "always")

    assert len(engine.requests) == 2
    assert [(e["page"], e["trigger"]) for e in ocr_events(sink)] == [(1, "forced"), (2, "forced")]
    assert report.conversions[0].ocr is not None
    # The book's text is what the engine read.
    assert report.conversions[0].output is not None
    text = text_of([p for body in chapters(Path(report.conversions[0].output)) for p in body])
    for paragraph in (source.with_suffix(".txt")).read_text(encoding="utf-8").split("\n\n"):
        assert squash(paragraph) in text


# --- Events and the report's OCR summary ------------------------------------------------


@pytest.mark.ac("OCR-AC24")
def test_ocr_events_and_summary_are_filled_in(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install(monkeypatch, FakeEngine(words_of(BORN_DIGITAL / "two-pages.pdf", 300)))

    report, sink = convert(
        [(SCANNED / "two-pages.pdf", "scan.pdf"), (BORN_DIGITAL / "two-pages.pdf", "typeset.pdf")],
        tmp_path,
    )

    scan, typeset = report.conversions
    assert scan.outcome is Outcome.CONVERTED
    events = ocr_events(sink, scan.id)
    assert len(events) == 2
    for event in events:
        assert isinstance(event["confidence"], float)
        assert isinstance(event["coverage"], float)
        assert isinstance(event["attempts"], int) and event["attempts"] >= 1
        assert isinstance(event["fell_back"], bool)
        assert event["trigger"] == "no_text_layer"
        # Every word the engine returned is the fake's, at its confidence; its boxes are
        # where the scan's ink is, so nearly all the ink is covered.
        assert event["confidence"] == pytest.approx(CONFIDENCE)
        assert event["coverage"] > 0.9
        assert event["fell_back"] is False
    [finished, _] = sink.of_type("conversion_finished")
    assert finished["ocr"] == {
        "engine": "tesseract",
        "engine_version": "5.3.4",
        "languages": ["eng"],
        "quality": "balanced",
    }
    assert typeset.ocr is None
    assert ocr_events(sink, typeset.id) == []
    assert scan.output is not None
    with zipfile.ZipFile(scan.output) as archive:
        opf = archive.read("OEBPS/content.opf").decode("utf-8")
    assert not re.search("ocr|tesseract", opf, re.IGNORECASE)


# --- Empty OCR results ------------------------------------------------------------------


@pytest.mark.ac("OCR-AC25")
def test_an_empty_ocr_result_keeps_a_good_text_layer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = BORN_DIGITAL / "two-pages.pdf"
    engine = install(monkeypatch, FakeEngine(no_words))

    report, _ = convert([(source, "book.pdf")], tmp_path, "always")

    [result] = report.conversions
    assert result.outcome is Outcome.CONVERTED
    assert len(engine.requests) == 2
    assert "page_fallback" not in issue_codes(report)
    assert result.output is not None
    pages = page_contents(Path(result.output))
    paragraphs = source.with_suffix(".txt").read_text(encoding="utf-8").split("\n\n")
    for number, paragraph in enumerate(paragraphs, start=1):
        assert squash(paragraph) in text_of(pages[number])


@pytest.mark.ac("OCR-AC25")
def test_a_blank_scanned_page_raises_no_issue(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def first_page_only(call: int, request: OcrRequest) -> OcrPageResult:
        return one_line(call, request) if call == 0 else no_words(call, request)

    engine = install(monkeypatch, FakeEngine(first_page_only))

    report, sink = convert([(SCANNED / "blank-page.pdf", "scan.pdf")], tmp_path)

    [result] = report.conversions
    assert result.outcome is Outcome.CONVERTED
    # Both pages are scans: both go to the engine, which finds nothing on page 2.
    assert len(engine.requests) == 2
    assert [e["page"] for e in ocr_events(sink)] == [1, 2]
    assert result.issues == []


# --- Headings in OCR'd text -------------------------------------------------------------


def outline_titles(pdf: Path) -> list[str]:
    document = pdfium.PdfDocument(pdf)
    try:
        return [item.get_title() for item in document.get_toc() if item.level == 0]
    finally:
        document.close()


@pytest.mark.ac("RFL-AC14")
def test_ocred_chapter_titles_are_level_1_headings_without_marks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    novel = BORN_DIGITAL / "novel.pdf"
    titles = outline_titles(novel)
    assert len(titles) == 10
    install(monkeypatch, FakeEngine(words_of(novel, 300, centre=lambda line: line in titles)))

    report, _ = convert([(SCANNED / "novel-clean.pdf", "scan.pdf")], tmp_path)

    [result] = report.conversions
    assert result.outcome is Outcome.CONVERTED, result.issues
    assert result.output is not None
    bodies = chapters(Path(result.output))
    level_1 = [
        squash("".join(map(str, heading.itertext())))
        for body in bodies
        if body.find(f".//{XHTML}nav") is None  # the navigation document's own heading
        for heading in body.iter(f"{XHTML}h1")
    ]
    assert level_1 == titles
    # The section titles are taller too, but set mid-page at the left margin: neither
    # centred nor at the top of a page, so not headings (RFL-R21).
    lower = [h for body in bodies for h in body.iter(*(f"{XHTML}h{n}" for n in range(2, 7)))]
    assert lower == []
    marks = [e for body in bodies for e in body.iter(*(f"{XHTML}{t}" for t in MARKS))]
    assert marks == []


# --- Columns on OCR'd pages -------------------------------------------------------------


@pytest.mark.ac("RFL-AC8")
def test_a_scanned_two_column_page_falls_back_with_column_ordered_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = BORN_DIGITAL / "two-column.pdf"
    install(monkeypatch, FakeEngine(words_of(source, 300)))
    truth = source.with_suffix(".txt").read_text(encoding="utf-8")
    # Pages 2-4 are set in two columns (fixturegen/layouts.py); the truth lists each
    # column's paragraphs after a [left] or [right] marker.
    columns: dict[int, dict[str, str]] = {}
    pattern = r"\[page (\d+): two-column\]\n\n(.*?)(?=\[page|\Z)"
    for number, body in re.findall(pattern, truth, re.S):
        left, right = body.split("[right]")
        columns[int(number)] = {
            "left": squash(left.replace("[left]", "")),
            "right": squash(right),
        }
    assert sorted(columns) == [2, 3, 4]

    report, sink = convert([(SCANNED / "two-column.pdf", "scan.pdf")], tmp_path)

    [result] = report.conversions
    fallbacks = {i.reason: i.pages for i in result.issues if str(i.code) == "page_fallback"}
    assert fallbacks == {"multi_column": [2, 3, 4]}
    assert [e["fell_back"] for e in ocr_events(sink)] == [False, True, True, True]
    assert result.output is not None
    pages = page_contents(Path(result.output))
    for number, sides in columns.items():
        [figure] = pages[number]
        assert figure.tag == f"{XHTML}figure"
        text = text_of([figure])
        # The whole left column, then the whole right column: never interleaved.
        assert sides["left"] in text
        assert sides["right"] in text
        assert text.index(sides["left"]) + len(sides["left"]) <= text.index(sides["right"])
