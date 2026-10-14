"""Usage errors end the run with exit code 2 before any conversion starts (BAT-R25,
CLI-R3)."""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import NOVEL

PDF2EPUB = Path(sys.executable).with_name("pdf2epub")


def run(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(PDF2EPUB), *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )


@pytest.mark.ac("BAT-AC18")
@pytest.mark.parametrize(
    ("args", "reason"),
    [
        (["--no-such-flag", "a.pdf"], "--no-such-flag"),
        (["--files-from", "missing-list.txt"], "missing-list.txt"),
        (["a.pdf", "b.pdf", "-o", "existing.txt"], "existing.txt"),
        ([], "no inputs"),
    ],
    ids=["unknown-flag", "missing-files-from", "output-is-a-file", "no-inputs"],
)
def test_usage_error_exits_2_with_a_reason_and_converts_nothing(
    tmp_path: Path, args: list[str], reason: str
) -> None:
    shutil.copyfile(NOVEL, tmp_path / "a.pdf")
    shutil.copyfile(NOVEL, tmp_path / "b.pdf")
    (tmp_path / "existing.txt").write_bytes(b"not touched")

    proc = run(args, tmp_path)

    assert proc.returncode == 2, proc.stderr
    assert reason in proc.stderr
    assert proc.stdout == ""
    assert sorted(p.name for p in tmp_path.iterdir()) == ["a.pdf", "b.pdf", "existing.txt"]
    assert (tmp_path / "existing.txt").read_bytes() == b"not touched"
