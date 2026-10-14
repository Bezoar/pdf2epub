"""``pdf2epub sample.pdf`` run as a subprocess: streams, exit code, the EPUB and the
one-line result (CLI-R1, CLI-R2, CLI-R3, CLI-R16)."""

import re
import subprocess
import sys
from pathlib import Path

import pytest

PDF2EPUB = Path(sys.executable).with_name("pdf2epub")
RESULT_LINE = re.compile(r"✓ .*sample.pdf → .*sample.epub \(\d+ pages, [\d.]+s\)")


def run(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args, cwd=cwd, capture_output=True, text=True, encoding="utf-8", check=False
    )


@pytest.mark.ac("CLI-AC1")
def test_pdf2epub_writes_the_epub_with_empty_stdout_and_exit_0(
    sample_pdf: Path, tmp_path: Path
) -> None:
    proc = run([str(PDF2EPUB), "sample.pdf"], cwd=tmp_path)

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == ""
    assert RESULT_LINE.search(proc.stderr), proc.stderr
    assert (tmp_path / "sample.epub").is_file()


@pytest.mark.ac("CLI-AC1")
def test_python_dash_m_with_overwrite_gives_the_same_result(
    sample_pdf: Path, tmp_path: Path
) -> None:
    first = run([str(PDF2EPUB), "sample.pdf"], cwd=tmp_path)
    assert first.returncode == 0, first.stderr
    epub = tmp_path / "sample.epub"
    epub.write_bytes(b"stale")

    proc = run([sys.executable, "-m", "pdf2epub", "sample.pdf", "--overwrite"], cwd=tmp_path)

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == ""
    assert RESULT_LINE.search(proc.stderr), proc.stderr
    assert epub.read_bytes().startswith(b"PK")


@pytest.mark.ac("CLI-AC15")
def test_single_conversion_report_is_one_result_line(sample_pdf: Path, tmp_path: Path) -> None:
    proc = run([str(PDF2EPUB), "sample.pdf"], cwd=tmp_path)

    assert proc.returncode == 0, proc.stderr
    lines = proc.stderr.splitlines()
    assert len(lines) == 1, proc.stderr
    match = RESULT_LINE.fullmatch(lines[0])
    assert match, lines[0]
    source, output = str(tmp_path / "sample.pdf"), str(tmp_path / "sample.epub")
    assert lines[0].startswith(f"✓ {source} → {output} (18 pages, ")
