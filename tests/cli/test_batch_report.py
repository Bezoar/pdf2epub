"""The batch report on stderr: totals, failures, and condensed warnings for converted
files (CLI-R15)."""

import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import FIXTURES, NOVEL
from pypdf import PdfReader, PdfWriter
from pypdf.generic import NameObject

PDF2EPUB = Path(sys.executable).with_name("pdf2epub")


def without_language(source: Path, target: Path) -> None:
    """Copy ``source`` with its catalog ``/Lang`` removed."""
    writer = PdfWriter(clone_from=PdfReader(source))
    del writer._root_object[NameObject("/Lang")]
    with target.open("wb") as file:
        writer.write(file)


def test_batch_report_lists_warnings_of_converted_files(tmp_path: Path) -> None:
    shutil.copyfile(NOVEL, tmp_path / "a.pdf")
    without_language(NOVEL, tmp_path / "b.pdf")

    proc = subprocess.run(
        [str(PDF2EPUB), "a.pdf", "b.pdf"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )

    assert proc.returncode == 0, proc.stderr
    lines = proc.stderr.splitlines()
    assert lines[0] == "Converted: 2  Skipped: 0  Failed: 0"
    warnings = [line for line in lines if line.startswith("! ")]
    assert warnings == [f"! {tmp_path / 'b.pdf'}: language_defaulted"]
    assert not any(re.match(r"[✓✗-] ", line) for line in lines)


def test_verbose_batch_report_lists_each_success(tmp_path: Path) -> None:
    shutil.copyfile(NOVEL, tmp_path / "a.pdf")
    shutil.copyfile(NOVEL, tmp_path / "b.pdf")

    proc = subprocess.run(
        [str(PDF2EPUB), "-v", "--overwrite", "a.pdf", "b.pdf"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )

    assert proc.returncode == 0, proc.stderr
    # -v also logs at INFO, so the report follows the log lines.
    lines = [line for line in proc.stderr.splitlines() if not line.startswith("INFO: ")]
    assert lines[0] == "Converted: 2  Skipped: 0  Failed: 0"
    successes = [line for line in lines if line.startswith("✓ ")]
    assert successes == [f"✓ {tmp_path / name}.pdf → {tmp_path / name}.epub" for name in ("a", "b")]


# --- CLI-AC14: totals, failures first, condensed warnings ------------------------------

MISSING_PAGE = FIXTURES / "scanned" / "page-numbers-missing.pdf"
TRUNCATED = FIXTURES / "damaged" / "truncated.pdf"


def mixed_batch(tmp_path: Path) -> list[str]:
    """``a.pdf`` converts with a page-list warning (``page_sequence_gap`` on pages 16 and
    17, standing in for ``page_fallback`` until page fallback lands), ``b.pdf``'s EPUB
    already exists, and ``c.pdf`` is corrupt."""
    shutil.copyfile(MISSING_PAGE, tmp_path / "a.pdf")
    shutil.copyfile(NOVEL, tmp_path / "b.pdf")
    shutil.copyfile(TRUNCATED, tmp_path / "c.pdf")
    first = run_cli(["b.pdf"], tmp_path)
    assert first.returncode == 0, first.stderr
    return ["a.pdf", "b.pdf", "c.pdf"]


def run_cli(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(PDF2EPUB), *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )


@pytest.mark.ac("CLI-AC14")
def test_report_lists_totals_then_failures_then_condensed_warnings(tmp_path: Path) -> None:
    proc = run_cli(mixed_batch(tmp_path), tmp_path)

    assert proc.returncode == 1, proc.stderr
    lines = proc.stderr.splitlines()
    assert lines[0] == "Converted: 1  Skipped: 1  Failed: 1"
    assert lines[1] == f"✗ {tmp_path / 'c.pdf'}"
    assert lines[2].startswith("  corrupt_pdf [error]: ")
    assert lines[3] == f"! {tmp_path / 'a.pdf'}: page_sequence_gap pages 16–17"  # noqa: RUF001
    assert len(lines) == 4
    assert not any(line.startswith("✓") for line in lines)


@pytest.mark.ac("CLI-AC14")
def test_verbose_report_also_lists_successes_and_skips(tmp_path: Path) -> None:
    proc = run_cli(["-v", *mixed_batch(tmp_path)], tmp_path)

    assert proc.returncode == 1, proc.stderr
    lines = [line for line in proc.stderr.splitlines() if not line.startswith("INFO: ")]
    assert lines[0] == "Converted: 1  Skipped: 1  Failed: 1"
    assert lines[1] == f"✗ {tmp_path / 'c.pdf'}"
    assert lines[4:] == [
        f"✓ {tmp_path / 'a.pdf'} → {tmp_path / 'a.epub'}",
        f"- {tmp_path / 'b.pdf'}: output_exists",
    ]


@pytest.mark.ac("CLI-AC14")
def test_quiet_report_shows_only_totals_and_failures(tmp_path: Path) -> None:
    proc = run_cli(["-q", *mixed_batch(tmp_path)], tmp_path)

    assert proc.returncode == 1, proc.stderr
    lines = proc.stderr.splitlines()
    assert lines[0] == "Converted: 1  Skipped: 1  Failed: 1"
    assert lines[1] == f"✗ {tmp_path / 'c.pdf'}"
    assert lines[2].startswith("  corrupt_pdf [error]: ")
    assert len(lines) == 3


@pytest.mark.parametrize("flag", ["-v", "--debug"])
def test_quiet_with_verbose_or_debug_is_a_usage_error(tmp_path: Path, flag: str) -> None:
    shutil.copyfile(NOVEL, tmp_path / "a.pdf")

    proc = run_cli(["-q", flag, "a.pdf"], tmp_path)

    assert proc.returncode == 2
    assert "-q" in proc.stderr
    assert not (tmp_path / "a.epub").exists()


# --- BAT-AC17 through the CLI: --strict -----------------------------------------------


@pytest.mark.ac("BAT-AC17")
def test_strict_turns_a_warning_into_exit_1_and_still_writes_the_epub(tmp_path: Path) -> None:
    without_language(NOVEL, tmp_path / "b.pdf")

    plain = run_cli(["b.pdf"], tmp_path)
    assert plain.returncode == 0, plain.stderr

    proc = run_cli(["--strict", "--overwrite", "b.pdf"], tmp_path)

    assert proc.returncode == 1, proc.stderr
    assert "language_defaulted [warning]" in proc.stderr
    assert (tmp_path / "b.epub").is_file()
