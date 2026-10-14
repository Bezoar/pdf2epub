"""Input discovery and batch planning through ``plan_batch`` / ``run_batch`` (BAT-R1 to
BAT-R6, API-R2, API-R18)."""

import io
import os
import shutil
from pathlib import Path

import pytest
from conftest import FIXTURES, PUBLIC_DOMAIN_SAMPLE, RecordingSink

from pdf2epub import (
    BatchOptions,
    ConversionOptions,
    DiscoveryOptions,
    InputSpec,
    plan_batch,
    read_files_from,
    run_batch,
)

NOT_A_PDF = FIXTURES / "damaged" / "not-a-pdf.pdf"


def touch_pdf(path: Path) -> Path:
    """A file that passes the content check (BAT-R4); planning never parses it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"%PDF-1.7\n%%EOF\n")
    return path


def sources(paths: list[InputSpec], options: DiscoveryOptions | None = None) -> list[str]:
    plan = plan_batch(paths, options or DiscoveryOptions())
    return [conversion.source for conversion in plan.conversions]


@pytest.mark.ac("BAT-AC1")
def test_positional_inputs_then_files_from_lines_in_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in ("a.pdf", "b.pdf", "c.pdf"):
        touch_pdf(tmp_path / name)
    monkeypatch.chdir(tmp_path)
    listed = read_files_from("-", stdin=io.StringIO("# comment\n\n  b.pdf  \n"))

    plan = plan_batch([InputSpec("c.pdf"), InputSpec("a.pdf"), *listed], DiscoveryOptions())

    assert [c.source for c in plan.conversions] == [
        str(tmp_path / "c.pdf"),
        str(tmp_path / "a.pdf"),
        str(tmp_path / "b.pdf"),
    ]
    assert all(not c.issues for c in plan.conversions)


@pytest.mark.ac("BAT-AC1")
def test_files_from_list_is_read_from_a_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    touch_pdf(tmp_path / "x.pdf")
    (tmp_path / "list.txt").write_text("   # a comment\nx.pdf\n   \n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    listed = read_files_from("list.txt")

    assert sources(listed) == [str(tmp_path / "x.pdf")]
    assert all(spec.from_list for spec in listed)


@pytest.mark.ac("BAT-AC1")
def test_a_literal_glob_is_not_expanded_and_gets_not_found(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    touch_pdf(tmp_path / "a.pdf")
    monkeypatch.chdir(tmp_path)

    plan = plan_batch([InputSpec("*.pdf")], DiscoveryOptions())

    assert len(plan.conversions) == 1
    conversion = plan.conversions[0]
    assert conversion.source == str(tmp_path / "*.pdf")
    assert [issue.code for issue in conversion.issues] == ["not_found"]
    assert conversion.destination is None


@pytest.fixture
def scanned_folder(tmp_path: Path) -> Path:
    """The BAT-AC2 folder: one.PDF, .hidden.pdf, notes.txt, sub/two.pdf, link -> other/."""
    folder = tmp_path / "books"
    touch_pdf(folder / "one.PDF")
    touch_pdf(folder / ".hidden.pdf")
    (folder / "notes.txt").write_text("notes", encoding="utf-8")
    touch_pdf(folder / "sub" / "two.pdf")
    touch_pdf(folder / ".secret" / "four.pdf")
    touch_pdf(tmp_path / "other-folder" / "three.pdf")
    os.symlink(tmp_path / "other-folder", folder / "link", target_is_directory=True)
    return folder


@pytest.mark.ac("BAT-AC2")
def test_folder_is_scanned_one_level_deep_by_default(scanned_folder: Path) -> None:
    assert sources([InputSpec(scanned_folder)]) == [str(scanned_folder / "one.PDF")]


@pytest.mark.ac("BAT-AC2")
def test_recursive_scan_skips_hidden_entries_and_symlinked_folders(
    scanned_folder: Path,
) -> None:
    found = sources([InputSpec(scanned_folder)], DiscoveryOptions(recursive=True))

    assert found == [str(scanned_folder / "one.PDF"), str(scanned_folder / "sub" / "two.pdf")]


@pytest.mark.ac("BAT-AC4")
def test_folder_contents_are_naturally_sorted_and_duplicates_planned_once(
    tmp_path: Path,
) -> None:
    folder = tmp_path / "dir"
    for name in ("ch10.pdf", "ch2.pdf", "Ch1.pdf"):
        touch_pdf(folder / name)

    plan = plan_batch([InputSpec(folder), InputSpec(folder / "ch2.pdf")], DiscoveryOptions())

    assert [c.source for c in plan.conversions] == [
        str(folder / "Ch1.pdf"),
        str(folder / "ch2.pdf"),
        str(folder / "ch10.pdf"),
    ]
    assert [c.id for c in plan.conversions] == [0, 1, 2]


@pytest.mark.ac("BAT-AC4")
def test_a_symlink_to_a_planned_file_is_a_duplicate(tmp_path: Path) -> None:
    real = touch_pdf(tmp_path / "real.pdf")
    os.symlink(real, tmp_path / "alias.pdf")

    assert sources([InputSpec(tmp_path / "alias.pdf"), InputSpec(real)]) == [
        str(tmp_path / "alias.pdf")
    ]


@pytest.mark.ac("BAT-AC3")
def test_files_are_recognised_by_content_not_name(tmp_path: Path, sink: RecordingSink) -> None:
    book = tmp_path / "book.dat"
    shutil.copyfile(PUBLIC_DOMAIN_SAMPLE, book)
    fake = tmp_path / "fake.pdf"
    shutil.copyfile(NOT_A_PDF, fake)

    plan = plan_batch([InputSpec(book), InputSpec(fake)], DiscoveryOptions())
    report = run_batch(plan, BatchOptions(isolation="inprocess"), ConversionOptions(), sink)

    book_result, fake_result = report.conversions
    assert book_result.outcome == "converted"
    assert book_result.output == str(tmp_path / "book.epub")
    assert (tmp_path / "book.epub").is_file()
    assert fake_result.outcome == "failed"
    assert [issue.code for issue in fake_result.issues] == ["not_a_pdf"]

    types_and_ids = [(e["type"], e.get("id")) for e in sink.events]
    assert types_and_ids.index(("conversion_finished", 1)) < types_and_ids.index(
        ("conversion_started", 0)
    )
    assert ("conversion_started", 1) not in types_and_ids


@pytest.mark.ac("API-AC1")
def test_missing_input_is_planned_and_reported_right_after_batch_started(
    novel_pdf: Path, sink: RecordingSink
) -> None:
    missing = novel_pdf.with_name("missing.pdf")

    plan = plan_batch([InputSpec(novel_pdf), InputSpec(missing)], DiscoveryOptions())
    run_batch(plan, BatchOptions(isolation="inprocess"), ConversionOptions(), sink)

    assert [c.id for c in plan.conversions] == [0, 1]
    assert sink.events[0]["type"] == "batch_started"
    assert sink.events[0]["total"] == 2
    finished = sink.events[1]
    assert finished["type"] == "conversion_finished"
    assert finished["id"] == 1
    assert finished["outcome"] == "failed"
    assert [issue["code"] for issue in finished["issues"]] == ["not_found"]
    assert [e["id"] for e in sink.of_type("conversion_started")] == [0]
