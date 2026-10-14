"""Which Tesseract the CLI runs (CLI-R5) and its engine options (OCR-R25), through the CLI
as a subprocess.

Which program was used is seen from the outside: each candidate is a fake ``tesseract``
(``fake_tesseract.py``) logging its calls to its own file.
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import FIXTURES
from fake_tesseract import NO_WORDS, fake_tesseract

PDF2EPUB = Path(sys.executable).with_name("pdf2epub")
SCAN = FIXTURES / "scanned" / "image-only.pdf"
TESSERACT_ENV = "PDF2EPUB_TESSERACT"


def run(
    args: list[str], cwd: Path, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(PDF2EPUB), *args],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )


@pytest.mark.ac("CLI-AC4")
def test_the_tesseract_flag_beats_the_variable_which_beats_path(tmp_path: Path) -> None:
    shutil.copyfile(SCAN, tmp_path / "scan.pdf")
    logs = {name: tmp_path / f"{name}.jsonl" for name in ("flag", "env", "path")}
    programs = {
        name: fake_tesseract(tmp_path / name, NO_WORDS, log=log) for name, log in logs.items()
    }
    base = {
        name: value
        for name, value in os.environ.items()
        if name != TESSERACT_ENV and not name.startswith("PDF2EPUB_PASSWORD")
    }
    base["PATH"] = os.pathsep.join([str(programs["path"].parent), base.get("PATH", "")])
    with_variable = {**base, TESSERACT_ENV: str(programs["env"])}

    def used(args: list[str], env: dict[str, str]) -> list[str]:
        for log in logs.values():
            log.unlink(missing_ok=True)
        proc = run(["--json", "--overwrite", *args, "scan.pdf"], tmp_path, env)
        assert proc.returncode == 0, proc.stderr
        return [name for name, log in logs.items() if log.exists()]

    assert used(["--tesseract", str(programs["flag"])], with_variable) == ["flag"]
    assert used([], with_variable) == ["env"]
    assert used([], base) == ["path"]


@pytest.mark.tesseract
@pytest.mark.ac("OCR-AC21")
def test_an_unknown_engine_option_exits_2_and_a_known_one_runs(tmp_path: Path) -> None:
    shutil.copyfile(SCAN, tmp_path / "scan.pdf")

    proc = run(["--json", "--ocr-engine-opt", "tesseract.not_a_param=1", "scan.pdf"], tmp_path)

    assert proc.returncode == 2
    assert "not_a_param" in proc.stderr
    assert proc.stdout == ""  # no event: no conversion started
    assert sorted(p.name for p in tmp_path.iterdir()) == ["scan.pdf"]

    proc = run(
        ["--json", "--ocr-engine-opt", "tesseract.preserve_interword_spaces=1", "scan.pdf"],
        tmp_path,
    )

    assert proc.returncode == 0, proc.stderr
    events = [json.loads(line) for line in proc.stdout.splitlines()]
    [finished] = [e for e in events if e["type"] == "conversion_finished"]
    assert finished["outcome"] == "converted"
    assert finished["ocr"] is not None
    assert (tmp_path / "scan.epub").is_file()


def test_an_engine_option_without_its_engine_prefix_is_a_usage_error(tmp_path: Path) -> None:
    shutil.copyfile(SCAN, tmp_path / "scan.pdf")

    proc = run(["--ocr-engine-opt", "preserve_interword_spaces=1", "scan.pdf"], tmp_path)

    assert proc.returncode == 2
    assert "--ocr-engine-opt" in proc.stderr
    assert sorted(p.name for p in tmp_path.iterdir()) == ["scan.pdf"]
