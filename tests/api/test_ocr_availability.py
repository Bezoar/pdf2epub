"""Whether OCR can run: the run's preflight probes the engine once (OCR-R24, API-R29),
validates engine options (OCR-R25), and a missing engine degrades to ``ocr_unavailable``
(OCR-R24), through ``plan_batch`` / ``run_batch``.

A missing program is ``OcrOptions.tesseract_path`` naming a file that isn't there. A
present one is a fake ``tesseract`` (``fake_tesseract.py``) that logs every call, so the
probe can be counted across worker subprocesses too.
"""

import json
import shutil
from pathlib import Path
from typing import Any

import pytest
from conftest import FIXTURES, NOVEL, RecordingSink
from fake_tesseract import NO_WORDS, fake_tesseract

from pdf2epub import (
    BatchOptions,
    ConversionOptions,
    DiscoveryOptions,
    InputSpec,
    OcrOptions,
    Outcome,
    UsageError,
    plan_batch,
    run_batch,
)
from pdf2epub.ocr import tesseract
from pdf2epub.options import Isolation
from pdf2epub.results import BatchReport

SCANNED = FIXTURES / "scanned"


def batch(
    folder: Path, sources: list[Path], ocr: OcrOptions, isolation: Isolation = "inprocess"
) -> tuple[BatchReport, RecordingSink]:
    pdfs = []
    for number, source in enumerate(sources):
        pdfs.append(folder / f"{number}-{source.name}")
        shutil.copyfile(source, pdfs[-1])
    sink = RecordingSink()
    plan = plan_batch([InputSpec(pdf) for pdf in pdfs], DiscoveryOptions())
    report = run_batch(plan, BatchOptions(isolation=isolation), ConversionOptions(ocr=ocr), sink)
    return report, sink


def count_lookups(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    """Count how often the core looks for the Tesseract program (the engine probe), letting
    each lookup run as usual."""
    calls: list[Any] = []
    real = tesseract.find_tesseract

    def find_tesseract(options: OcrOptions) -> Any:
        calls.append(options)
        return real(options)

    monkeypatch.setattr(tesseract, "find_tesseract", find_tesseract)
    return calls


def calls_of(log: Path) -> list[list[str]]:
    """The argument lists the fake ``tesseract`` was called with."""
    if not log.exists():
        return []
    return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]


@pytest.mark.ac("OCR-AC19")
@pytest.mark.ac("API-AC17")
def test_missing_tesseract_degrades_to_ocr_unavailable_and_is_probed_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lookups = count_lookups(monkeypatch)
    missing = tmp_path / "no-such-folder" / "tesseract"

    report, _ = batch(
        tmp_path, [SCANNED / "two-pages.pdf", NOVEL], OcrOptions(tesseract_path=missing)
    )

    assert report.exit_code == 0
    scanned, born_digital = report.conversions
    assert scanned.outcome is Outcome.CONVERTED
    [unavailable] = [i for i in scanned.issues if i.code == "ocr_unavailable"]
    assert unavailable.severity == "warning"
    assert unavailable.pages == []
    assert unavailable.hint is not None
    assert "brew install tesseract" in unavailable.hint
    assert "apt install tesseract-ocr" in unavailable.hint
    fallbacks = [(i.reason, i.pages) for i in scanned.issues if i.code == "page_fallback"]
    assert fallbacks == [("ocr_unavailable", [1, 2])]
    assert scanned.ocr is None
    assert born_digital.outcome is Outcome.CONVERTED
    assert not [i for i in born_digital.issues if str(i.code).startswith(("ocr_", "page_"))]
    assert len(lookups) == 1


@pytest.mark.ac("OCR-AC19")
def test_tesseract_is_probed_once_per_batch_not_once_per_worker(tmp_path: Path) -> None:
    log = tmp_path / "calls.jsonl"
    program = fake_tesseract(tmp_path / "bin", NO_WORDS, log=log)

    report, _ = batch(
        tmp_path,
        [SCANNED / "two-pages.pdf", SCANNED / "image-only.pdf"],
        OcrOptions(tesseract_path=program),
        isolation="subprocess",
    )

    assert [r.outcome for r in report.conversions] == [Outcome.CONVERTED] * 2
    calls = calls_of(log)
    assert sum("--version" in argv for argv in calls) == 1
    assert sum("--list-langs" in argv for argv in calls) == 1
    recognitions = [argv for argv in calls if "stdin" in argv]
    assert len(recognitions) == 5  # two pages, then three


@pytest.mark.ac("API-AC17")
def test_an_unknown_engine_option_is_a_usage_error_before_any_event(tmp_path: Path) -> None:
    program = fake_tesseract(tmp_path / "bin", NO_WORDS)
    sink = RecordingSink()
    pdfs = [tmp_path / "a.pdf", tmp_path / "b.pdf"]
    for pdf in pdfs:
        shutil.copyfile(SCANNED / "two-pages.pdf", pdf)
    plan = plan_batch([InputSpec(pdf) for pdf in pdfs], DiscoveryOptions())
    options = OcrOptions(tesseract_path=program, engine_options={"tesseract.no_such_key": "1"})

    with pytest.raises(UsageError, match="no_such_key"):
        run_batch(plan, BatchOptions(isolation="inprocess"), ConversionOptions(ocr=options), sink)

    assert sink.events == []
    assert not list(tmp_path.glob("*.epub"))


def test_engine_options_are_refused_when_tesseract_lists_no_parameters(tmp_path: Path) -> None:
    program = fake_tesseract(tmp_path / "bin", NO_WORDS, parameters=())
    sink = RecordingSink()
    shutil.copyfile(SCANNED / "image-only.pdf", tmp_path / "a.pdf")
    plan = plan_batch([InputSpec(tmp_path / "a.pdf")], DiscoveryOptions())
    options = OcrOptions(
        tesseract_path=program, engine_options={"tesseract.preserve_interword_spaces": "1"}
    )

    with pytest.raises(UsageError, match="print-parameters"):
        run_batch(plan, BatchOptions(isolation="inprocess"), ConversionOptions(ocr=options), sink)

    assert sink.events == []


def test_a_known_engine_option_reaches_tesseract_without_its_namespace(tmp_path: Path) -> None:
    log = tmp_path / "calls.jsonl"
    program = fake_tesseract(tmp_path / "bin", NO_WORDS, log=log)
    options = OcrOptions(
        tesseract_path=program, engine_options={"tesseract.preserve_interword_spaces": "1"}
    )

    report, _ = batch(tmp_path, [SCANNED / "image-only.pdf"], options)

    assert report.conversions[0].outcome is Outcome.CONVERTED
    recognitions = [argv for argv in calls_of(log) if "stdin" in argv]
    assert len(recognitions) == 3
    for argv in recognitions:
        assert argv[argv.index("-c") + 1] == "preserve_interword_spaces=1"


def test_engine_options_are_ignored_when_tesseract_is_missing(tmp_path: Path) -> None:
    options = OcrOptions(
        tesseract_path=tmp_path / "missing", engine_options={"tesseract.no_such_key": "1"}
    )

    report, _ = batch(tmp_path, [SCANNED / "image-only.pdf"], options)

    [conversion] = report.conversions
    assert conversion.outcome is Outcome.CONVERTED
    assert "ocr_unavailable" in [i.code for i in conversion.issues]
