"""The OCR language and its availability (OCR-R24, OCR-R26): which languages the engine is
asked for, through ``plan_batch`` / ``run_batch`` with a fake engine, and what happens
when real Tesseract has no data for them.

The scanned fixture's declared language is set at test time, by writing ``/Lang`` into a
copy's catalog with pypdf.
"""

import shutil
from pathlib import Path

import pytest
from conftest import FIXTURES, RecordingSink
from fake_engine import FakeEngine, install
from pypdf import PdfReader, PdfWriter
from pypdf.generic import NameObject, TextStringObject

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
from pdf2epub.results import ConversionResult

SCAN = FIXTURES / "scanned" / "image-only.pdf"


def with_language(source: Path, target: Path, language: str | None) -> Path:
    """A copy of ``source`` whose catalog declares ``language`` (none if None)."""
    if language is None:
        shutil.copyfile(source, target)
        return target
    writer = PdfWriter(clone_from=PdfReader(source))
    writer._root_object[NameObject("/Lang")] = TextStringObject(language)
    with target.open("wb") as out:
        writer.write(out)
    return target


def convert(pdf: Path, options: ConversionOptions) -> ConversionResult:
    plan = plan_batch([InputSpec(pdf)], DiscoveryOptions())
    report = run_batch(plan, BatchOptions(isolation="inprocess"), options, RecordingSink())
    return report.conversions[0]


@pytest.mark.ac("OCR-AC22")
@pytest.mark.parametrize(
    ("declared", "options", "expected"),
    [
        ("de", ConversionOptions(), "deu"),
        ("de", ConversionOptions(language="fr"), "fra"),
        ("de", ConversionOptions(ocr=OcrOptions(languages="eng+fra")), "eng+fra"),
        (None, ConversionOptions(), "eng"),
    ],
    ids=["metadata", "book-language", "ocr-languages", "default"],
)
def test_the_ocr_language_follows_its_precedence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    declared: str | None,
    options: ConversionOptions,
    expected: str,
) -> None:
    engine = install(monkeypatch, FakeEngine())
    pdf = with_language(SCAN, tmp_path / "scan.pdf", declared)

    result = convert(pdf, options)

    assert result.outcome is Outcome.CONVERTED
    assert engine.requests
    assert {request.languages for request in engine.requests} == {expected}


@pytest.mark.parametrize(
    ("tag", "expected"),
    [
        ("de-DE", "deu"),
        ("deu", "deu"),
        ("fil", "fil"),
        ("zh-Hant", "chi_tra"),
        ("zh-CN", "chi_sim"),
        ("sr-Latn", "srp_latn"),
    ],
)
def test_book_language_tags_map_to_tesseract_codes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tag: str, expected: str
) -> None:
    engine = install(monkeypatch, FakeEngine())
    pdf = with_language(SCAN, tmp_path / "scan.pdf", None)

    convert(pdf, ConversionOptions(language=tag))

    assert {request.languages for request in engine.requests} == {expected}


def test_an_unmappable_language_falls_back_to_english(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = install(monkeypatch, FakeEngine())
    pdf = with_language(SCAN, tmp_path / "scan.pdf", "x-klingon")

    convert(pdf, ConversionOptions())

    assert {request.languages for request in engine.requests} == {"eng"}


@pytest.mark.tesseract
@pytest.mark.ac("OCR-AC20")
def test_missing_language_data_degrades_to_ocr_unavailable(tmp_path: Path) -> None:
    pdf = with_language(SCAN, tmp_path / "scan.pdf", None)

    result = convert(pdf, ConversionOptions(ocr=OcrOptions(languages="xyz")))

    assert result.outcome is Outcome.CONVERTED
    [unavailable] = [i for i in result.issues if i.code == "ocr_unavailable"]
    assert unavailable.hint is not None
    assert "tesseract-ocr-xyz" in unavailable.hint
    fallbacks = [(i.reason, i.pages) for i in result.issues if i.code == "page_fallback"]
    assert fallbacks == [("ocr_unavailable", [1, 2, 3])]
    assert result.ocr is None
