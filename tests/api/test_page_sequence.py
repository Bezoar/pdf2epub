"""Page sequence gaps (RFL-R29, RFL-R30): breaks in the printed page numbers are reported
as one ``page_sequence_gap`` warning, without false alarms on front matter, unnumbered
openers or plates. Driven through ``plan_batch`` / ``run_batch`` in-process.

The fixtures are the page-numbers scans: images under an invisible text layer whose folios
are known from the generator's design (see ``fixturegen/pagenumbers.py``).
"""

import shutil
from pathlib import Path
from typing import Any

import pytest
from conftest import FIXTURES, NOVEL, RecordingSink

from pdf2epub import (
    BatchOptions,
    ConversionOptions,
    ConversionResult,
    DiscoveryOptions,
    InputSpec,
    Outcome,
    plan_batch,
    run_batch,
)

SCANNED = FIXTURES / "scanned"
MISSING = SCANNED / "page-numbers-missing.pdf"
REPEATED = SCANNED / "page-numbers-repeated.pdf"
FRONT_MATTER = SCANNED / "page-numbers-front-matter.pdf"
PAGE_LABELS = FIXTURES / "born-digital" / "page-labels.pdf"


def convert(source: Path, folder: Path) -> tuple[ConversionResult, RecordingSink]:
    pdf = folder / source.name
    shutil.copyfile(source, pdf)
    sink = RecordingSink()
    plan = plan_batch([InputSpec(pdf)], DiscoveryOptions())
    report = run_batch(plan, BatchOptions(isolation="inprocess"), ConversionOptions(), sink)
    [result] = report.conversions
    return result, sink


def gap_issues(sink: RecordingSink) -> list[dict[str, Any]]:
    [finished] = sink.of_type("conversion_finished")
    return [i for i in finished["issues"] if i["code"] == "page_sequence_gap"]


@pytest.mark.ac("RFL-AC20")
def test_a_missing_printed_page_is_a_warning_naming_the_pages(tmp_path: Path) -> None:
    result, sink = convert(MISSING, tmp_path)

    assert result.outcome is Outcome.CONVERTED
    [gap] = gap_issues(sink)
    assert gap["severity"] == "warning"
    assert gap["pages"] == [16, 17]
    assert "printed page 17 is missing" in gap["message"]
    # The issue was also emitted as it was found.
    assert [e["issue"] for e in sink.of_type("issue")].count(gap) == 1


@pytest.mark.ac("RFL-AC20")
def test_a_repeated_printed_page_is_a_warning_naming_the_number(tmp_path: Path) -> None:
    result, sink = convert(REPEATED, tmp_path)

    assert result.outcome is Outcome.CONVERTED
    [gap] = gap_issues(sink)
    assert gap["severity"] == "warning"
    assert gap["pages"] == [9, 10]
    assert "printed page 9 is repeated" in gap["message"]


@pytest.mark.ac("RFL-AC21")
@pytest.mark.parametrize("source", [FRONT_MATTER, PAGE_LABELS, NOVEL], ids=lambda p: p.stem)
def test_front_matter_openers_and_plates_are_not_gaps(source: Path, tmp_path: Path) -> None:
    # The front-matter scan has roman folios i-x, then 1-40 with an unnumbered opener
    # where 13 would be and an unnumbered plate between 30 and 31; the page-labels book
    # switches from roman to arabic; the novel's openers all carry folios.
    result, sink = convert(source, tmp_path)

    assert result.outcome is Outcome.CONVERTED
    assert gap_issues(sink) == []
