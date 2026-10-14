"""The text-layer quality check, at the ``OcrEngine`` seam with a fake engine and through
the Python API (OCR-R3, OCR-R5 to OCR-R10, OCR-R31).

The must-trust set (OCR-AC3) is every born-digital fixture with a text layer and every
scan with a good invisible OCR layer; the must-reject set is the three fixtures under
``tests/fixtures/must-reject/`` (TST-R3, TST-R4). What each fixture is comes from its
generator (``fixturegen/textlayers.py`` for the new ones), never from pdf2epub.
"""

import re
import shutil
import zipfile
from pathlib import Path

import pytest
from conftest import FIXTURES, RecordingSink
from fake_engine import FakeEngine, install, no_words
from test_routing import (
    BORN_DIGITAL,
    SCANNED,
    XHTML,
    ocr_events,
    one_line,
    page_contents,
    squash,
    text_of,
)

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
from pdf2epub.issues import Issue, Severity
from pdf2epub.ocr.engine import EngineFailed, OcrLine, OcrPageResult, OcrRequest, Word
from pdf2epub.results import BatchReport

MUST_REJECT = FIXTURES / "must-reject"
NO_TOUNICODE = MUST_REJECT / "no-tounicode.pdf"
GARBLED_LAYER = MUST_REJECT / "garbled-layer.pdf"
HALF_LAYER = MUST_REJECT / "half-layer.pdf"
ALL_PAGES = [1, 2, 3, 4]
# The born-digital fixtures with no text layer at all are not must-trust text layers.
_NO_TEXT_LAYER = {"image-only.pdf", "blank-pages.pdf"}
MUST_TRUST = [
    *sorted(p for p in BORN_DIGITAL.glob("*.pdf") if p.name not in _NO_TEXT_LAYER),
    SCANNED / "ocr-layer.pdf",
    *sorted(SCANNED.glob("page-numbers-*.pdf")),
]
# Characters that are never text: Private Use Area code points and U+FFFD.
GARBAGE = re.compile("[-\U000f0000-\U0010ffff�]")


def convert(
    source: Path,
    folder: Path,
    mode: str = "auto",
    language: str | None = None,
    ocr_languages: str | None = None,
) -> tuple[BatchReport, RecordingSink]:
    """Convert a copy of ``source`` in OCR ``mode`` (and book ``language`` and OCR
    ``ocr_languages``, if given)."""
    shutil.copyfile(source, folder / source.name)
    sink = RecordingSink()
    plan = plan_batch([InputSpec(folder / source.name)], DiscoveryOptions())
    ocr = OcrOptions(mode=mode, languages=ocr_languages)  # type: ignore[arg-type]
    options = ConversionOptions(language=language, ocr=ocr)
    report = run_batch(plan, BatchOptions(isolation="inprocess"), options, sink)
    return report, sink


def issues_of(report: BatchReport, code: str) -> list[Issue]:
    return [issue for issue in report.conversions[0].issues if str(issue.code) == code]


def rejections(report: BatchReport) -> dict[str | None, list[int]]:
    return {i.reason: i.pages for i in issues_of(report, "text_layer_rejected")}


def fallbacks(report: BatchReport) -> dict[str | None, list[int]]:
    return {i.reason: i.pages for i in issues_of(report, "page_fallback")}


def epub_text(epub: Path) -> str:
    with zipfile.ZipFile(epub) as archive:
        return "".join(
            archive.read(name).decode("utf-8")
            for name in archive.namelist()
            if name.endswith(".xhtml")
        )


def truth_words(source: Path) -> set[str]:
    return set(re.findall(r"[A-Za-z]+", source.with_suffix(".txt").read_text(encoding="utf-8")))


# --- The must-trust set ----------------------------------------------------------------


@pytest.mark.ac("OCR-AC3")
@pytest.mark.parametrize("source", MUST_TRUST, ids=lambda path: f"{path.parent.name}/{path.name}")
def test_every_must_trust_page_is_trusted(
    source: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = install(monkeypatch, FakeEngine(one_line))

    report, sink = convert(source, tmp_path)

    assert report.conversions[0].outcome is Outcome.CONVERTED
    assert issues_of(report, "text_layer_rejected") == []
    # Pages with (almost) no text layer over a large image are OCR'd directly, unchecked
    # (OCR-R1): the front-matter scan's plate. No page with a text layer is OCR'd.
    direct = [e for e in ocr_events(sink) if e["trigger"] == "no_text_layer"]
    assert ocr_events(sink) == direct
    assert len(engine.requests) == len(direct)


# --- The must-reject set ---------------------------------------------------------------


@pytest.mark.ac("OCR-AC4")
def test_a_font_with_no_tounicode_map_is_rejected_as_garbled_on_every_page(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install(monkeypatch, FakeEngine(one_line))

    report, sink = convert(NO_TOUNICODE, tmp_path)

    [issue] = issues_of(report, "text_layer_rejected")
    assert issue.severity is Severity.INFO
    assert (issue.reason, issue.pages) == ("garbled", ALL_PAGES)
    assert [(e["page"], e["trigger"]) for e in ocr_events(sink)] == [
        (page, "text_layer_rejected") for page in ALL_PAGES
    ]


@pytest.mark.ac("OCR-AC5")
def test_a_half_page_invisible_layer_is_rejected_as_low_coverage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install(monkeypatch, FakeEngine(one_line))

    report, sink = convert(HALF_LAYER, tmp_path)

    assert rejections(report) == {"low_coverage": ALL_PAGES}
    assert [(e["page"], e["trigger"]) for e in ocr_events(sink)] == [
        (page, "text_layer_rejected") for page in ALL_PAGES
    ]


@pytest.mark.ac("OCR-AC6")
def test_a_nonsense_word_invisible_layer_is_rejected_as_implausible_words(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install(monkeypatch, FakeEngine(one_line))

    report, sink = convert(GARBLED_LAYER, tmp_path)

    assert rejections(report) == {"implausible_words": ALL_PAGES}
    assert [e["trigger"] for e in ocr_events(sink)] == ["text_layer_rejected"] * 4


def test_letters_of_a_script_the_ocr_language_does_not_use_are_garbage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # OCR-R7.1: the Japanese and Korean sample, said to be English, is all mismatched
    # script.
    install(monkeypatch, FakeEngine(one_line))

    report, _ = convert(BORN_DIGITAL / "cjk-lines.pdf", tmp_path, language="en")

    assert rejections(report) == {"garbled": [1]}


def test_a_tesseract_script_model_names_the_script_of_the_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install(monkeypatch, FakeEngine(one_line))

    report, _ = convert(BORN_DIGITAL / "cjk-lines.pdf", tmp_path, ocr_languages="script/Latin")

    assert rejections(report) == {"garbled": [1]}


# --- Languages with no wordlist --------------------------------------------------------


@pytest.mark.ac("OCR-AC7")
@pytest.mark.parametrize(
    ("source", "language"),
    [
        (BORN_DIGITAL / "cjk-lines.pdf", None),  # Japanese and Korean (declared ja)
        (BORN_DIGITAL / "two-pages.pdf", "fr"),  # Latin script, a language with no list
        (BORN_DIGITAL / "two-pages.pdf", "de"),
    ],
)
def test_valid_text_in_a_language_with_no_wordlist_is_never_rejected(
    source: Path, language: str | None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = install(monkeypatch, FakeEngine(one_line))

    report, sink = convert(source, tmp_path, language=language)

    assert issues_of(report, "text_layer_rejected") == []
    assert ocr_events(sink) == []
    assert engine.requests == []


# --- mode = "never" --------------------------------------------------------------------


@pytest.mark.ac("OCR-AC9")
def test_never_runs_no_ocr_and_rejected_pages_fall_back_bad_text_layer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = install(monkeypatch, FakeEngine(one_line))

    report, sink = convert(NO_TOUNICODE, tmp_path, "never")

    [result] = report.conversions
    assert engine.requests == []
    assert ocr_events(sink) == []
    assert result.outcome is Outcome.CONVERTED
    [issue] = issues_of(report, "page_fallback")
    assert issue.severity is Severity.WARNING
    assert (issue.reason, issue.pages) == ("bad_text_layer", ALL_PAGES)
    assert result.output is not None
    text = epub_text(Path(result.output))
    assert not GARBAGE.search(text)
    # The layer's text is garbage even without such characters: none of it is kept.
    pages = page_contents(Path(result.output))
    for number in ALL_PAGES:
        [figure] = pages[number]
        assert figure.tag == f"{XHTML}figure"
        assert figure.find(f".//{XHTML}div") is None  # no hidden text


@pytest.mark.ac("OCR-AC9")
def test_never_makes_pages_that_would_be_ocred_directly_bad_text_layer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = install(monkeypatch, FakeEngine(one_line))

    report, _ = convert(SCANNED / "image-only.pdf", tmp_path, "never")

    assert engine.requests == []
    assert report.conversions[0].outcome is Outcome.CONVERTED
    assert fallbacks(report) == {"bad_text_layer": [1, 2, 3]}


# --- Hidden text of a page with a rejected layer (OCR-R10, OCR-R31) --------------------


@pytest.mark.ac("OCR-AC25")
def test_an_empty_ocr_result_on_a_rejected_layer_leaves_a_page_image_with_no_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install(monkeypatch, FakeEngine(no_words))

    report, _ = convert(GARBLED_LAYER, tmp_path, "always")

    [result] = report.conversions
    # The check runs and reports under ``always`` too (OCR-R9).
    assert rejections(report) == {"implausible_words": ALL_PAGES}
    assert fallbacks(report) == {"ocr_low_confidence": ALL_PAGES}
    assert result.output is not None
    pages = page_contents(Path(result.output))
    for number in ALL_PAGES:
        [figure] = pages[number]
        assert figure.tag == f"{XHTML}figure"
        assert figure.find(f".//{XHTML}div") is None  # no hidden text


def garbage_reading(call: int, request: OcrRequest) -> OcrPageResult:
    """Every attempt: two words of Private Use Area garbage, low confidence, far from most
    of the ink."""
    words = (
        Word("", 10, 10, 60, 40, 0.30, 30),
        Word("", 70, 10, 130, 40, 0.30, 30),
    )
    return OcrPageResult(lines=(OcrLine(words, 30),))


def faint_reading(call: int, request: OcrRequest) -> OcrPageResult:
    """Every attempt: two plain English words, low confidence, far from most of the ink."""
    words = (Word("Faint", 10, 10, 60, 40, 0.30, 30), Word("words", 70, 10, 130, 40, 0.30, 30))
    return OcrPageResult(lines=(OcrLine(words, 30),))


@pytest.mark.ac("OCR-AC10")
def test_a_rejected_prior_ocr_layer_with_less_garbage_is_the_hidden_text_under_auto(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The half-page layer is rejected (low coverage) but clean; OCR reads garbage.
    engine = install(monkeypatch, FakeEngine(garbage_reading))

    report, sink = convert(HALF_LAYER, tmp_path)

    [result] = report.conversions
    assert rejections(report) == {"low_coverage": ALL_PAGES}
    assert fallbacks(report) == {"ocr_low_confidence": ALL_PAGES}
    assert len(engine.requests) == 16
    assert [(e["attempts"], e["fell_back"]) for e in ocr_events(sink)] == [(4, True)] * 4
    assert result.output is not None
    pages = page_contents(Path(result.output))
    for number in ALL_PAGES:
        [figure] = pages[number]
        hidden = text_of([figure])
        assert "The Harbour Ledger" in hidden
        assert not GARBAGE.search(hidden)


def test_a_layer_rejected_as_garbled_is_never_the_hidden_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install(monkeypatch, FakeEngine(faint_reading))

    report, _ = convert(NO_TOUNICODE, tmp_path)

    [result] = report.conversions
    assert fallbacks(report) == {"ocr_low_confidence": ALL_PAGES}
    assert result.output is not None
    pages = page_contents(Path(result.output))
    for number in ALL_PAGES:
        assert text_of(pages[number]).endswith("Faint words")


def test_hidden_text_with_no_garbage_either_way_is_the_more_plausible(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The nonsense-word layer has no garbage characters, and nor does OCR's reading; the
    # reading's words are English, the layer's are not.
    install(monkeypatch, FakeEngine(faint_reading))

    report, _ = convert(GARBLED_LAYER, tmp_path)

    [result] = report.conversions
    assert result.output is not None
    pages = page_contents(Path(result.output))
    for number in ALL_PAGES:
        assert text_of(pages[number]).endswith("Faint words")


def test_a_failed_ocr_page_never_keeps_a_garbled_layer_as_hidden_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def failing(call: int, request: OcrRequest) -> OcrPageResult:
        raise EngineFailed("exit status 1")

    install(monkeypatch, FakeEngine(failing))

    report, _ = convert(NO_TOUNICODE, tmp_path)

    [result] = report.conversions
    assert fallbacks(report) == {"ocr_failed": ALL_PAGES}
    assert result.output is not None
    pages = page_contents(Path(result.output))
    for number in ALL_PAGES:
        [figure] = pages[number]
        assert figure.find(f".//{XHTML}div") is None  # no hidden text


def test_a_failed_ocr_page_keeps_a_rejected_but_clean_layer_as_hidden_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def failing(call: int, request: OcrRequest) -> OcrPageResult:
        raise EngineFailed("exit status 1")

    install(monkeypatch, FakeEngine(failing))

    report, _ = convert(HALF_LAYER, tmp_path)

    [result] = report.conversions
    assert fallbacks(report) == {"ocr_failed": ALL_PAGES}
    assert result.output is not None
    words = truth_words(HALF_LAYER)
    pages = page_contents(Path(result.output))
    for number in ALL_PAGES:
        hidden = squash(text_of(pages[number]))
        assert "The Harbour Ledger" in hidden
        header = {"Harbour", "Ledger"}  # the running header
        assert set(re.findall(r"[A-Za-z]+", hidden)) <= words | header
