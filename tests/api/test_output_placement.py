"""Where each EPUB goes, when a conversion is skipped, and how it is written, through
``plan_batch`` / ``run_batch`` (BAT-R9 to BAT-R16, BAT-R23, EPUB-R18)."""

import os
import shutil
import stat
import zipfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from conftest import FIXTURES, NOVEL, PUBLIC_DOMAIN_SAMPLE, RecordingSink

from pdf2epub import (
    BatchOptions,
    BatchReport,
    CancelToken,
    ConversionOptions,
    DiscoveryOptions,
    InputSpec,
    IssueCode,
    Outcome,
    Severity,
    plan_batch,
    run_batch,
)

TRUNCATED = FIXTURES / "damaged" / "truncated.pdf"


def run(
    inputs: list[Path],
    sink: RecordingSink | None = None,
    *,
    recursive: bool = False,
    output: Path | None = None,
    overwrite: bool = False,
    cancel: CancelToken | None = None,
) -> BatchReport:
    plan = plan_batch(
        [InputSpec(path) for path in inputs], DiscoveryOptions(recursive=recursive, output=output)
    )
    return run_batch(
        plan,
        BatchOptions(isolation="inprocess", overwrite=overwrite),
        ConversionOptions(),
        sink if sink is not None else RecordingSink(),
        cancel=cancel,
    )


def copy(source: Path, target: Path) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)
    return target


def codes(report: BatchReport) -> list[list[IssueCode]]:
    return [[issue.code for issue in result.issues] for result in report.conversions]


def files_in(folder: Path) -> set[str]:
    return {path.relative_to(folder).as_posix() for path in folder.rglob("*") if path.is_file()}


@pytest.fixture
def read_only() -> Iterator[list[Path]]:
    """Folders a test makes read-only; their permissions are restored at teardown."""
    folders: list[Path] = []
    yield folders
    for folder in folders:
        folder.chmod(stat.S_IRWXU)


def make_read_only(folder: Path, registry: list[Path]) -> None:
    folder.chmod(stat.S_IRUSR | stat.S_IXUSR)
    registry.append(folder)
    if os.access(folder, os.W_OK):  # e.g. running as root
        pytest.skip("this user can write to read-only folders")


# --- BAT-AC6: placement --------------------------------------------------------------


@pytest.fixture
def books(tmp_path: Path) -> Path:
    folder = tmp_path / "books"
    copy(PUBLIC_DOMAIN_SAMPLE, folder / "a.pdf")
    copy(NOVEL, folder / "sub" / "b.pdf")
    return folder


@pytest.mark.ac("BAT-AC6")
def test_recursive_batch_writes_each_epub_next_to_its_pdf(books: Path) -> None:
    report = run([books], recursive=True)

    assert report.exit_code == 0
    assert [r.output for r in report.conversions] == [
        str(books / "a.epub"),
        str(books / "sub" / "b.epub"),
    ]
    assert files_in(books) == {"a.pdf", "a.epub", "sub/b.pdf", "sub/b.epub"}


@pytest.mark.ac("BAT-AC6")
def test_batch_output_folder_is_created_and_mirrors_the_tree(books: Path, tmp_path: Path) -> None:
    out = tmp_path / "out"

    report = run([books], recursive=True, output=out)

    assert report.exit_code == 0
    assert [r.output for r in report.conversions] == [
        str(out / "a.epub"),
        str(out / "sub" / "b.epub"),
    ]
    assert files_in(out) == {"a.epub", "sub/b.epub"}
    assert files_in(books) == {"a.pdf", "sub/b.pdf"}


@pytest.mark.ac("BAT-AC6")
def test_files_named_explicitly_go_directly_into_the_output_folder(
    books: Path, tmp_path: Path
) -> None:
    out = tmp_path / "out"

    report = run([books / "a.pdf", books / "sub" / "b.pdf"], output=out)

    assert report.exit_code == 0
    assert files_in(out) == {"a.epub", "b.epub"}


@pytest.mark.ac("BAT-AC6")
def test_single_conversion_output_names_the_epub_file(books: Path, tmp_path: Path) -> None:
    target = tmp_path / "x" / "My Book.epub"

    report = run([books / "a.pdf"], output=target)

    assert report.exit_code == 0
    assert report.conversions[0].output == str(target)
    assert files_in(tmp_path / "x") == {"My Book.epub"}


# --- BAT-AC7: collisions -------------------------------------------------------------


@pytest.mark.ac("BAT-AC7")
def test_second_input_mapping_to_the_same_epub_is_skipped_as_a_collision(
    tmp_path: Path, sink: RecordingSink
) -> None:
    one = copy(PUBLIC_DOMAIN_SAMPLE, tmp_path / "one" / "book.pdf")
    two = copy(NOVEL, tmp_path / "two" / "book.pdf")
    out = tmp_path / "out"

    report = run([one, two], sink, output=out)

    first, second = report.conversions
    assert (first.source, first.outcome, first.output) == (
        str(one),
        Outcome.CONVERTED,
        str(out / "book.epub"),
    )
    assert second.source == str(two)
    assert second.outcome is Outcome.SKIPPED
    assert [(i.code, i.severity) for i in second.issues] == [
        (IssueCode.OUTPUT_COLLISION, Severity.INFO)
    ]
    assert second.output is None
    assert report.exit_code == 0
    assert files_in(out) == {"book.epub"}
    # Decided at planning time: reported before any conversion starts (API-R18).
    types = [(e["type"], e.get("id")) for e in sink.events]
    assert types.index(("conversion_finished", 1)) < types.index(("conversion_started", 0))
    assert ("conversion_started", 1) not in types


@pytest.mark.ac("BAT-AC7")
def test_collision_holds_with_overwrite_when_the_epub_exists(tmp_path: Path) -> None:
    one = copy(PUBLIC_DOMAIN_SAMPLE, tmp_path / "one" / "book.pdf")
    two = copy(NOVEL, tmp_path / "two" / "book.pdf")
    out = tmp_path / "out"
    run([one], output=out / "book.epub")

    report = run([one, two], output=out, overwrite=True)

    assert codes(report) == [[], [IssueCode.OUTPUT_COLLISION]]
    assert [r.outcome for r in report.conversions] == [Outcome.CONVERTED, Outcome.SKIPPED]


@pytest.mark.ac("BAT-AC7")
def test_destinations_reached_through_a_folder_link_collide(tmp_path: Path) -> None:
    real = tmp_path / "real"
    first = copy(PUBLIC_DOMAIN_SAMPLE, real / "book.pdf")
    copy(NOVEL, real / "book.dat")
    (tmp_path / "alias").symlink_to(real, target_is_directory=True)

    report = run([first, tmp_path / "alias" / "book.dat"])

    assert codes(report) == [[], [IssueCode.OUTPUT_COLLISION]]
    assert files_in(real) == {"book.pdf", "book.dat", "book.epub"}


def case_insensitive(folder: Path) -> bool:
    """Whether ``folder``'s file system ignores letter case, found by experiment."""
    probe = folder / "Case-Probe"
    probe.touch()
    try:
        return (folder / "case-probe").exists()
    finally:
        probe.unlink()


@pytest.mark.ac("BAT-AC7")
def test_destinations_differing_only_in_case_collide_where_case_is_ignored(
    tmp_path: Path,
) -> None:
    one = copy(PUBLIC_DOMAIN_SAMPLE, tmp_path / "one" / "book.pdf")
    two = copy(NOVEL, tmp_path / "two" / "BOOK.PDF")
    out = tmp_path / "out"
    out.mkdir()
    ignores_case = case_insensitive(out)

    report = run([one, two], output=out)

    if ignores_case:  # e.g. macOS: out/BOOK.epub is out/book.epub
        assert codes(report) == [[], [IssueCode.OUTPUT_COLLISION]]
        assert files_in(out) == {"book.epub"}
    else:
        assert codes(report) == [[], []]
        assert files_in(out) == {"book.epub", "BOOK.epub"}


# --- BAT-AC8: existing EPUBs and resume ----------------------------------------------


@pytest.mark.ac("BAT-AC8")
def test_existing_epubs_are_skipped_rerun_resumes_and_overwrite_replaces(tmp_path: Path) -> None:
    shelf = tmp_path / "shelf"
    for name in ("a", "b", "c"):
        copy(NOVEL, shelf / f"{name}.pdf")
    stale = b"an earlier, unrelated b.epub"
    (shelf / "b.epub").write_bytes(stale)

    first = run([shelf])

    assert codes(first) == [[], [IssueCode.OUTPUT_EXISTS], []]
    assert [r.outcome for r in first.conversions] == [
        Outcome.CONVERTED,
        Outcome.SKIPPED,
        Outcome.CONVERTED,
    ]
    assert first.exit_code == 0
    assert (shelf / "b.epub").read_bytes() == stale

    again = run([shelf])

    assert codes(again) == [[IssueCode.OUTPUT_EXISTS]] * 3
    assert {r.outcome for r in again.conversions} == {Outcome.SKIPPED}
    assert again.exit_code == 0

    replaced = run([shelf], overwrite=True)

    assert codes(replaced) == [[], [], []]
    assert {r.outcome for r in replaced.conversions} == {Outcome.CONVERTED}
    assert replaced.exit_code == 0
    assert replaced.conversions[1].output == str(shelf / "b.epub")
    with zipfile.ZipFile(shelf / "b.epub") as epub:
        assert epub.read("mimetype") == b"application/epub+zip"
    assert files_in(shelf) == {"a.pdf", "b.pdf", "c.pdf", "a.epub", "b.epub", "c.epub"}


# --- BAT-AC9: a failure or cancellation never harms the destination ------------------


@pytest.mark.ac("BAT-AC9")
def test_failed_conversion_with_overwrite_leaves_the_existing_epub_untouched(
    tmp_path: Path,
) -> None:
    elsewhere = tmp_path / "elsewhere"
    known = run([copy(NOVEL, elsewhere / "novel.pdf")]).conversions[0].output
    assert known is not None
    folder = tmp_path / "shelf"
    bad = copy(TRUNCATED, folder / "bad.pdf")
    existing = copy(Path(known), folder / "bad.epub").read_bytes()

    report = run([bad], overwrite=True)

    assert report.conversions[0].outcome is Outcome.FAILED
    assert report.exit_code == 1
    assert (folder / "bad.epub").read_bytes() == existing
    assert sorted(os.listdir(folder)) == ["bad.epub", "bad.pdf"]


@pytest.mark.ac("BAT-AC9")
def test_conversion_cancelled_in_its_write_stage_leaves_no_file(tmp_path: Path) -> None:
    folder = tmp_path / "shelf"
    good = copy(NOVEL, folder / "good.pdf")
    cancel = CancelToken()
    sink = RecordingSink()

    def cancel_when_reflow_ends(event: dict[str, Any]) -> None:
        sink(event)
        if event["type"] == "progress" and event["stage"] == "reflow":
            cancel.cancel()  # the next stage is write

    plan = plan_batch([InputSpec(good)], DiscoveryOptions())
    report = run_batch(
        plan,
        BatchOptions(isolation="inprocess"),
        ConversionOptions(),
        cancel_when_reflow_ends,
        cancel=cancel,
    )

    assert report.interrupted
    assert report.exit_code == 130
    assert codes(report) == [[IssueCode.NOT_ATTEMPTED]]
    assert report.conversions[0].output is None
    assert sorted(os.listdir(folder)) == ["good.pdf"]


# --- BAT-AC10, EPUB-AC12: unwritable destinations ------------------------------------


@pytest.mark.ac("BAT-AC10")
@pytest.mark.ac("EPUB-AC12")
def test_unwritable_output_folder_fails_write_failed_naming_the_destination(
    tmp_path: Path, read_only: list[Path]
) -> None:
    folder = tmp_path / "locked"
    novel = copy(NOVEL, folder / "novel.pdf")
    make_read_only(folder, read_only)

    report = run([novel])

    [result] = report.conversions
    assert result.outcome is Outcome.FAILED
    [issue] = result.issues
    assert (issue.code, issue.severity) == (IssueCode.WRITE_FAILED, Severity.ERROR)
    assert str(folder / "novel.epub") in issue.message
    assert os.strerror(13) in issue.message  # EACCES, the operating-system reason
    assert result.output is None
    assert report.exit_code == 1
    assert sorted(os.listdir(folder)) == ["novel.pdf"]


@pytest.mark.ac("BAT-AC10")
def test_folder_at_the_destination_fails_write_failed_not_output_exists(tmp_path: Path) -> None:
    folder = tmp_path / "shelf"
    novel = copy(NOVEL, folder / "novel.pdf")
    (folder / "novel.epub").mkdir()

    report = run([novel])

    assert codes(report) == [[IssueCode.WRITE_FAILED]]
    assert str(folder / "novel.epub") in report.conversions[0].issues[0].message
    assert report.exit_code == 1
    assert sorted(os.listdir(folder)) == ["novel.epub", "novel.pdf"]


@pytest.mark.ac("BAT-AC10")
def test_output_folder_that_cannot_be_created_fails_write_failed(
    tmp_path: Path, read_only: list[Path]
) -> None:
    novel = copy(NOVEL, tmp_path / "in" / "novel.pdf")
    parent = tmp_path / "locked"
    parent.mkdir()
    make_read_only(parent, read_only)

    report = run([novel, copy(NOVEL, tmp_path / "in" / "other.pdf")], output=parent / "out")

    assert codes(report) == [[IssueCode.WRITE_FAILED]] * 2
    assert str(parent / "out" / "novel.epub") in report.conversions[0].issues[0].message
    assert report.exit_code == 1


# --- BAT-AC16: defaults --------------------------------------------------------------


@pytest.mark.ac("BAT-AC16")
def test_discovery_and_batch_options_have_the_specified_defaults() -> None:
    discovery, batch = DiscoveryOptions(), BatchOptions()

    assert discovery.recursive is False
    assert discovery.output is None
    assert batch.timeout == 1800
    assert batch.overwrite is False
    assert batch.isolation == "subprocess"
    assert batch.strict is False
