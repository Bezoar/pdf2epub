"""The suite-wide epubcheck sweep in tests/conftest.py (TST-R19): an invalid EPUB that a
test writes under its ``tmp_path`` fails the suite, naming the EPUB and the test."""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import _epubcheck_command

TESTS = Path(__file__).resolve().parents[1]

WRITES_AN_INVALID_EPUB = """
def test_writes_an_invalid_epub(tmp_path):
    (tmp_path / "invalid.epub").write_bytes(b"not a zip file")
"""


def test_an_invalid_epub_under_tmp_path_fails_the_test_that_wrote_it(
    tmp_path: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    if _epubcheck_command() is None:
        pytest.skip("epubcheck is not available: set EPUBCHECK_JAR or put it on PATH")
    # A separate pytest run with this suite's conftest, whose own tmp_path lies outside
    # this test's tmp_path, so this test's sweep doesn't see the invalid EPUB.
    shutil.copyfile(TESTS / "conftest.py", tmp_path / "conftest.py")
    shutil.copytree(TESTS / "epubcheck", tmp_path / "epubcheck")
    (tmp_path / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    (tmp_path / "test_inner.py").write_text(WRITES_AN_INVALID_EPUB, encoding="utf-8")
    basetemp = tmp_path_factory.mktemp("inner")
    env = dict(os.environ)
    if env.get("EPUBCHECK_JAR"):  # the inner run has another working directory
        env["EPUBCHECK_JAR"] = str(Path(env["EPUBCHECK_JAR"]).resolve())

    run = subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", f"--basetemp={basetemp}"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert run.returncode == 1, run.stdout + run.stderr
    assert "ERROR at teardown of test_writes_an_invalid_epub" in run.stdout
    rejected = f"epubcheck rejected {basetemp}/test_writes_an_invalid_epub0/invalid.epub"
    assert rejected in run.stdout
    assert "PKG-" in run.stdout  # epubcheck's own message IDs are quoted
