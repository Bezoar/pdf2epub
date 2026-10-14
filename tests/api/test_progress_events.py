"""Progress stages and conversion ids in the event stream (API-R21, API-R27)."""

from pathlib import Path

import pytest
from conftest import RecordingSink
from pypdf import PdfReader, PdfWriter

from pdf2epub import (
    BatchOptions,
    ConversionOptions,
    DiscoveryOptions,
    InputSpec,
    plan_batch,
    run_batch,
)

CONVERSION_EVENTS = {
    "conversion_started",
    "progress",
    "password_required",
    "password_request",
    "conversion_finished",
}


def first_pages(source: Path, count: int, target: Path) -> Path:
    """Copy the first ``count`` pages of ``source`` to ``target``."""
    writer = PdfWriter()
    for page in PdfReader(source).pages[:count]:
        writer.add_page(page)
    with target.open("wb") as file:
        writer.write(file)
    return target


def run(pdfs: list[Path], sink: RecordingSink) -> None:
    plan = plan_batch([InputSpec(pdf) for pdf in pdfs], DiscoveryOptions())
    run_batch(plan, BatchOptions(isolation="inprocess"), ConversionOptions(), sink)


@pytest.mark.ac("API-AC11")
def test_born_digital_conversion_passes_open_analyse_reflow_write_without_ocr(
    sample_pdf: Path, tmp_path: Path, sink: RecordingSink
) -> None:
    three_pages = first_pages(sample_pdf, 3, tmp_path / "three.pdf")

    run([three_pages], sink)

    progress = [(e["stage"], e["done"], e["of"], e.get("page")) for e in sink.of_type("progress")]
    assert progress == [
        ("open", 1, 1, None),
        ("analyse", 1, 3, 1),
        ("analyse", 2, 3, 2),
        ("analyse", 3, 3, 3),
        ("reflow", 1, 1, None),
        ("write", 1, 1, None),
    ]
    assert all(e["id"] == 0 for e in sink.of_type("progress"))
    [finished] = sink.of_type("conversion_finished")
    assert finished["outcome"] == "converted"


@pytest.mark.ac("API-AC15")
def test_every_conversion_event_carries_a_planned_integer_id_and_jobs_is_1(
    sample_pdf: Path, novel_pdf: Path, sink: RecordingSink
) -> None:
    run([sample_pdf, novel_pdf], sink)

    [started] = sink.of_type("batch_started")
    assert started["jobs"] == 1
    assert [p["id"] for p in started["planned"]] == [0, 1]
    scoped = [e for e in sink.events if e["type"] in CONVERSION_EVENTS]
    assert {e["type"] for e in scoped} >= {"conversion_started", "progress", "conversion_finished"}
    for event in scoped:
        assert type(event["id"]) is int, event
        assert event["id"] in {0, 1}, event
    assert {e["id"] for e in sink.of_type("conversion_finished")} == {0, 1}
