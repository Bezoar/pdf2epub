"""A single conversion prints one result line; any other run prints the batch report,
with the same events and exit code (BAT-R7, BAT-R8)."""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import PUBLIC_DOMAIN_SAMPLE
from test_json_output import events_of

PDF2EPUB = Path(sys.executable).with_name("pdf2epub")


def run(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(PDF2EPUB), *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8"
    )


def book_in(folder: Path) -> Path:
    folder.mkdir(parents=True)
    return Path(shutil.copyfile(PUBLIC_DOMAIN_SAMPLE, folder / "book.pdf"))


@pytest.mark.ac("BAT-AC5")
def test_named_file_prints_one_line_and_folder_prints_the_batch_report(tmp_path: Path) -> None:
    single = book_in(tmp_path / "single")
    shelf = book_in(tmp_path / "shelf").parent

    named = run([str(single)], cwd=tmp_path)
    folder = run([str(shelf)], cwd=tmp_path)

    assert named.returncode == 0, named.stderr
    [line] = named.stderr.splitlines()
    assert line.startswith(f"✓ {single} → {single.with_suffix('.epub')} (")
    assert folder.returncode == 0, folder.stderr
    assert folder.stderr.splitlines() == ["Converted: 1  Skipped: 0  Failed: 0"]
    assert (shelf / "book.epub").is_file()


@pytest.mark.ac("BAT-AC5")
def test_named_file_and_folder_emit_the_same_event_types(tmp_path: Path) -> None:
    single = book_in(tmp_path / "single")
    shelf = book_in(tmp_path / "shelf").parent

    named = run(["--json", str(single)], cwd=tmp_path)
    folder = run(["--json", str(shelf)], cwd=tmp_path)

    assert named.returncode == folder.returncode == 0, named.stderr + folder.stderr
    named_types = [event["type"] for event in events_of(named.stdout)]
    folder_types = [event["type"] for event in events_of(folder.stdout)]
    assert named_types == folder_types
    assert named_types[0] == "batch_started"
    assert named_types[-1] == "batch_finished"
    assert "conversion_finished" in named_types
