"""The flag surface: each flag sets exactly its core option and nothing else (CLI-R4), and
each forbidden flag combination is a usage error (CLI-R7), through the CLI as a
subprocess.

The options the CLI hands the core are captured by a test hook in the CLI process
(``worker_hooks.capture_environment``), which stops it before the batch runs.
"""

import os
import pickle
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import worker_hooks
from conftest import PUBLIC_DOMAIN_SAMPLE

from pdf2epub.options import BatchOptions, ConversionOptions, DiscoveryOptions, OcrOptions

PDF2EPUB = Path(sys.executable).with_name("pdf2epub")


def clean_environment() -> dict[str, str]:
    """The test's environment without pdf2epub's own variables, which would set options."""
    return {name: value for name, value in os.environ.items() if not name.startswith("PDF2EPUB_")}


def captured_options(args: list[str], cwd: Path) -> dict[str, Any]:
    record = cwd / "options.pickle"
    proc = subprocess.run(
        [str(PDF2EPUB), *args, "sample.pdf"],
        cwd=cwd,
        env=worker_hooks.capture_environment(record, clean_environment()),
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    options: dict[str, Any] = pickle.loads(record.read_bytes())
    return options


@pytest.fixture
def sample(tmp_path: Path) -> Path:
    shutil.copyfile(PUBLIC_DOMAIN_SAMPLE, tmp_path / "sample.pdf")
    return tmp_path / "sample.pdf"


@pytest.mark.ac("CLI-AC3")
def test_without_optional_flags_every_option_is_the_core_default(
    tmp_path: Path, sample: Path
) -> None:
    options = captured_options([], tmp_path)

    assert options["discovery"] == DiscoveryOptions()
    assert options["batch"] == BatchOptions()
    assert options["conversion"] == ConversionOptions()
    assert options["conversion"].ocr == OcrOptions()


@pytest.mark.ac("CLI-AC3")
def test_each_flag_sets_its_option(tmp_path: Path, sample: Path) -> None:
    options = captured_options(
        [
            *["-r", "-o", "out", "--overwrite", "--timeout", "60", "--strict"],
            *["--mode", "reflow", "--title", "T", "--author", "A", "--author", "B"],
            *["--language", "de", "--cover", "none"],
            *["--ocr", "always", "--ocr-lang", "fra+eng", "--ocr-quality", "best"],
            *["--ocr-page-timeout", "90", "--ocr-min-confidence", "0.8"],
            *["--ocr-engine-opt", "tesseract.preserve_interword_spaces=1"],
            *["--tessdata-dir", "td", "--tesseract", "/flag/tess"],
        ],
        tmp_path,
    )

    assert options["discovery"] == DiscoveryOptions(recursive=True, output=Path("out"))
    assert options["batch"] == BatchOptions(timeout=60, overwrite=True, strict=True)
    assert options["conversion"] == ConversionOptions(
        mode="reflow",
        language="de",
        title="T",
        authors=["A", "B"],
        cover=None,
        ocr=OcrOptions(
            mode="always",
            languages="fra+eng",
            quality="best",
            page_timeout=90,
            min_confidence=0.8,
            engine_options={"preserve_interword_spaces": "1"},
            tesseract_path=Path("/flag/tess"),
            tessdata_dir=Path("td"),
        ),
    )


@pytest.mark.ac("CLI-AC3")
def test_a_cover_path_is_the_cover_option(tmp_path: Path, sample: Path) -> None:
    options = captured_options(["--cover", "front.png"], tmp_path)

    assert options["conversion"] == ConversionOptions(cover=Path("front.png"))


# One run per CLI-R7 combination; every other argument is valid.
FORBIDDEN = {
    "interactive-without-json": ["--interactive", "sample.pdf"],
    "interactive-files-from-stdin": ["--json", "--interactive", "--files-from", "-"],
    "ask-password-with-json": ["--json", "--ask-password", "sample.pdf"],
    "ask-password-without-terminal": ["--ask-password", "sample.pdf"],
    "quiet-verbose": ["-q", "-v", "sample.pdf"],
    "quiet-debug": ["-q", "--debug", "sample.pdf"],
    "engine-opt-without-prefix": ["--ocr-engine-opt", "preserve_interword_spaces=1", "sample.pdf"],
    "engine-opt-without-equals": [
        "--ocr-engine-opt",
        "tesseract.preserve_interword_spaces",
        "sample.pdf",
    ],
    "min-confidence-above-1": ["--ocr-min-confidence", "1.5", "sample.pdf"],
    "min-confidence-below-0": ["--ocr-min-confidence", "-0.1", "sample.pdf"],
    "min-confidence-not-a-number": ["--ocr-min-confidence", "nan", "sample.pdf"],
    "timeout-0": ["--timeout", "0", "sample.pdf"],
    "timeout-negative": ["--timeout", "-5", "sample.pdf"],
    "ocr-page-timeout-0": ["--ocr-page-timeout", "0", "sample.pdf"],
    "ocr-page-timeout-negative": ["--ocr-page-timeout", "-5", "sample.pdf"],
    "no-inputs": [],
}


@pytest.mark.ac("CLI-AC6")
@pytest.mark.parametrize("args", FORBIDDEN.values(), ids=FORBIDDEN.keys())
def test_a_forbidden_combination_is_a_usage_error(
    tmp_path: Path, sample: Path, args: list[str]
) -> None:
    proc = subprocess.run(
        [str(PDF2EPUB), *args],
        cwd=tmp_path,
        env=clean_environment(),
        input="sample.pdf\n",  # stdin is a pipe, not a terminal
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )

    assert proc.returncode == 2, proc.stderr
    assert proc.stderr.startswith("usage: pdf2epub")
    assert "error:" in proc.stderr
    assert "unrecognized arguments" not in proc.stderr  # refused for the combination
    assert proc.stdout == ""
    assert sorted(p.name for p in tmp_path.iterdir()) == ["sample.pdf"]
