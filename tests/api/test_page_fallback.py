"""Page fallbacks are reported as one ``page_fallback`` issue per reason (API-R11), driven
through ``plan_batch`` / ``run_batch`` in-process.

The fixture's page kinds come from its generator (see ``fixturegen/layouts.py``): a table
on page 3, two columns on page 5 and equations on page 7.
"""

import shutil
from pathlib import Path

import pytest
from conftest import FIXTURES, RecordingSink

from pdf2epub import (
    BatchOptions,
    ConversionOptions,
    DiscoveryOptions,
    InputSpec,
    Outcome,
    plan_batch,
    run_batch,
)

FALLBACKS = FIXTURES / "born-digital" / "fallbacks.pdf"


@pytest.mark.ac("API-AC8")
def test_fallbacks_are_grouped_by_reason_with_sorted_pages(tmp_path: Path) -> None:
    pdf = tmp_path / FALLBACKS.name
    shutil.copyfile(FALLBACKS, pdf)
    sink = RecordingSink()
    plan = plan_batch([InputSpec(pdf)], DiscoveryOptions())

    report = run_batch(plan, BatchOptions(isolation="inprocess"), ConversionOptions(), sink)

    [result] = report.conversions
    assert result.outcome is Outcome.CONVERTED
    [finished] = sink.of_type("conversion_finished")
    fallbacks = [i for i in finished["issues"] if i["code"] == "page_fallback"]
    assert sorted((i["reason"], i["pages"]) for i in fallbacks) == [
        ("complex", [3, 7]),
        ("multi_column", [5]),
    ]
    assert all(i["severity"] == "warning" for i in fallbacks)
