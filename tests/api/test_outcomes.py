"""Options, outcomes and exit codes (API-R9, API-R10, API-R12, BAT-R24): frozen options
with core defaults, outcomes derived from issue sets, fixed severities, and the batch's
exit code, driven through ``plan_batch`` / ``run_batch`` in-process."""

import dataclasses
import shutil
from pathlib import Path
from typing import Any

import pytest
from conftest import FIXTURES, NOVEL, RecordingSink
from pypdf import PdfReader, PdfWriter
from pypdf.generic import NameObject

from pdf2epub import (
    BatchOptions,
    BatchReport,
    ConversionOptions,
    DiscoveryOptions,
    InputSpec,
    Issue,
    IssueCode,
    OcrOptions,
    Outcome,
    Severity,
    plan_batch,
    run_batch,
)
from pdf2epub.issues import derive_outcome

# The registry table of API §6.1, copied by hand: code -> severity.
REGISTRY = {
    "missing_password": "error",
    "wrong_password": "error",
    "restricted": "error",
    "drm_protected": "error",
    "unsupported_encryption": "error",
    "owner_password_used": "info",
    "not_found": "error",
    "not_a_pdf": "error",
    "corrupt_pdf": "error",
    "repaired_pdf": "warning",
    "empty_document": "error",
    "resource_limit": "error",
    "output_exists": "info",
    "output_collision": "info",
    "write_failed": "error",
    "page_fallback": "warning",
    "language_defaulted": "warning",
    "page_sequence_gap": "warning",
    "ocr_unavailable": "warning",
    "ocr_timeout": "warning",
    "ocr_failed": "warning",
    "text_layer_rejected": "info",
    "not_attempted": "info",
    "timeout": "error",
    "internal_error": "error",
}

OPTIONS_CLASSES = [DiscoveryOptions, BatchOptions, ConversionOptions, OcrOptions]


@pytest.mark.ac("API-AC6")
@pytest.mark.parametrize("cls", OPTIONS_CLASSES, ids=lambda c: c.__name__)
def test_options_construct_with_defaults_and_are_frozen(cls: Any) -> None:
    options = cls()

    fields = dataclasses.fields(options)
    assert fields, cls
    for field in fields:
        with pytest.raises(dataclasses.FrozenInstanceError):
            setattr(options, field.name, getattr(options, field.name))


def issue(code: str) -> Issue:
    return Issue(IssueCode(code), "message")


@pytest.mark.ac("API-AC7")
@pytest.mark.parametrize(
    ("codes", "outcome"),
    [
        (["page_fallback"], "converted"),
        (["output_exists"], "skipped"),
        (["restricted"], "failed"),
        (["not_attempted"], "skipped"),
        (["missing_password", "page_fallback"], "failed"),
        ([], "converted"),
    ],
)
def test_outcome_is_derived_from_the_issue_set(codes: list[str], outcome: str) -> None:
    assert derive_outcome([issue(code) for code in codes]) == Outcome(outcome)


@pytest.mark.ac("API-AC7")
def test_every_issue_code_has_its_registry_severity() -> None:
    assert {str(code) for code in IssueCode} == set(REGISTRY)
    for code, severity in REGISTRY.items():
        assert IssueCode(code).severity is Severity(severity), code
        assert issue(code).severity is Severity(severity), code
        assert issue(code).to_dict()["severity"] == severity, code


def without_language(source: Path, target: Path) -> None:
    """Copy ``source`` with its catalog ``/Lang`` removed, so it converts with a
    ``language_defaulted`` warning."""
    writer = PdfWriter(clone_from=PdfReader(source))
    del writer._root_object[NameObject("/Lang")]
    with target.open("wb") as file:
        writer.write(file)


def run(sources: list[Path], **batch: Any) -> tuple[BatchReport, RecordingSink]:
    sink = RecordingSink()
    plan = plan_batch([InputSpec(source) for source in sources], DiscoveryOptions())
    report = run_batch(
        plan, BatchOptions(isolation="inprocess", **batch), ConversionOptions(), sink
    )
    [finished] = sink.of_type("batch_finished")
    assert finished["exit_code"] == report.exit_code
    return report, sink


# Until page fallback (#38) lands, a warning stands in for page_fallback: BAT-R24 depends
# only on the severity and the outcome.


@pytest.mark.ac("BAT-AC17")
@pytest.mark.parametrize("strict", [False, True])
def test_converted_with_a_warning_exits_0_or_1_under_strict(tmp_path: Path, strict: bool) -> None:
    shutil.copyfile(NOVEL, tmp_path / "a.pdf")
    without_language(NOVEL, tmp_path / "b.pdf")

    report, _ = run([tmp_path / "a.pdf", tmp_path / "b.pdf"], strict=strict)

    assert [r.outcome for r in report.conversions] == [Outcome.CONVERTED] * 2
    assert [i.severity for i in report.conversions[1].issues] == [Severity.WARNING]
    assert report.exit_code == (1 if strict else 0)
    assert (tmp_path / "b.epub").is_file()
    assert report.conversions[1].output == str(tmp_path / "b.epub")


@pytest.mark.ac("BAT-AC17")
def test_one_missing_password_failure_among_conversions_exits_1(tmp_path: Path) -> None:
    shutil.copyfile(NOVEL, tmp_path / "a.pdf")
    shutil.copyfile(FIXTURES / "encrypted" / "aes256-user.pdf", tmp_path / "b.pdf")
    shutil.copyfile(NOVEL, tmp_path / "c.pdf")

    report, _ = run([tmp_path / name for name in ("a.pdf", "b.pdf", "c.pdf")])

    outcomes = [r.outcome for r in report.conversions]
    assert outcomes == [Outcome.CONVERTED, Outcome.FAILED, Outcome.CONVERTED]
    assert [i.code for i in report.conversions[1].issues] == [IssueCode.MISSING_PASSWORD]
    assert report.exit_code == 1


@pytest.mark.ac("BAT-AC17")
@pytest.mark.parametrize("strict", [False, True])
def test_only_output_exists_skips_exit_0(tmp_path: Path, strict: bool) -> None:
    sources = [tmp_path / "a.pdf", tmp_path / "b.pdf"]
    for source in sources:
        shutil.copyfile(NOVEL, source)
    first, _ = run(sources)  # writes both EPUBs
    assert first.exit_code == 0

    report, _ = run(sources, strict=strict)

    assert [r.outcome for r in report.conversions] == [Outcome.SKIPPED] * 2
    assert report.exit_code == 0
