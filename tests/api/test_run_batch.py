"""``plan_batch`` / ``run_batch`` driven in-process with a recording sink (API-R3, API-R4,
API-R16, API-R17)."""

import threading
from pathlib import Path

import pytest
from conftest import RecordingSink

from pdf2epub import (
    BatchOptions,
    BatchReport,
    ConversionOptions,
    DiscoveryOptions,
    InputSpec,
    plan_batch,
    run_batch,
)

ENVELOPE = ("v", "type", "t")


def run_on_own_thread(pdf: Path, sink: RecordingSink) -> tuple[BatchReport, int]:
    """Call ``run_batch`` from a fresh thread and return its report and that thread's id."""
    result: list[tuple[BatchReport, int]] = []

    def worker() -> None:
        plan = plan_batch([InputSpec(pdf)], DiscoveryOptions())
        report = run_batch(plan, BatchOptions(isolation="inprocess"), ConversionOptions(), sink)
        result.append((report, threading.get_ident()))

    thread = threading.Thread(target=worker)
    thread.start()
    thread.join()
    assert result, "run_batch raised on its thread"
    return result[0]


@pytest.mark.ac("API-AC2")
def test_inprocess_run_emits_one_bracketed_stream_on_the_calling_thread(
    novel_pdf: Path, sink: RecordingSink
) -> None:
    _, caller = run_on_own_thread(novel_pdf, sink)

    types = [event["type"] for event in sink.events]
    assert types[0] == "batch_started"
    assert types[-1] == "batch_finished"
    assert types.count("batch_started") == types.count("batch_finished") == 1
    assert [e["id"] for e in sink.of_type("conversion_started")] == [0]
    assert [e["id"] for e in sink.of_type("conversion_finished")] == [0]
    assert all(event["v"] == 1 for event in sink.events)
    times = [event["t"] for event in sink.events]
    assert times == sorted(times)
    assert sink.threads == {caller}


@pytest.mark.ac("API-AC2")
def test_returned_report_equals_the_batch_finished_payload(
    novel_pdf: Path, sink: RecordingSink
) -> None:
    report, _ = run_on_own_thread(novel_pdf, sink)

    finished = sink.events[-1]
    payload = {key: value for key, value in finished.items() if key not in ENVELOPE}
    assert report.to_dict() == payload
    assert payload["exit_code"] == 0
    assert payload["totals"] == {"converted": 1, "skipped": 0, "failed": 0}
    [conversion] = payload["conversions"]
    assert conversion["outcome"] == "converted"
    assert conversion["source"] == str(novel_pdf)
    assert conversion["output"] == str(novel_pdf.with_suffix(".epub"))
    assert novel_pdf.with_suffix(".epub").is_file()
    assert conversion["pages"] == 40


@pytest.mark.ac("API-AC2")
def test_conversion_events_follow_the_v1_catalogue(novel_pdf: Path, sink: RecordingSink) -> None:
    run_on_own_thread(novel_pdf, sink)

    [started] = sink.of_type("batch_started")
    assert started["total"] == 1
    assert started["jobs"] == 1
    assert started["planned"] == [
        {"id": 0, "source": str(novel_pdf), "destination": str(novel_pdf.with_suffix(".epub"))}
    ]
    stages = [(e["stage"], e["done"], e["of"]) for e in sink.of_type("progress")]
    assert stages[0] == ("open", 1, 1)
    assert stages[-2:] == [("reflow", 1, 1), ("write", 1, 1)]
    assert [(s, d, o) for s, d, o in stages if s == "analyse"] == [
        ("analyse", n, 40) for n in range(1, 41)
    ]
    [finished] = sink.of_type("conversion_finished")
    assert set(finished) - set(ENVELOPE) == {
        "id",
        "source",
        "destination",
        "outcome",
        "output",
        "issues",
        "password_source",
        "pages",
        "duration",
        "ocr",
    }
