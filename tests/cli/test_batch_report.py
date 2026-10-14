"""The batch report on stderr: totals, failures, and condensed warnings for converted
files (CLI-R15)."""

import re
import shutil
import subprocess
import sys
from pathlib import Path

from conftest import NOVEL
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
