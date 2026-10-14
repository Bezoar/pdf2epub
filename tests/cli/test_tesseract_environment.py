"""What the OCR engine's subprocess is given when the CLI runs it: never the password
(PWD-R25)."""

import json
import subprocess
import sys
from pathlib import Path

import pytest
import worker_hooks
from conftest import FIXTURES
from fake_tesseract import fake_tesseract, record
from pypdf import PdfReader, PdfWriter

PDF2EPUB = Path(sys.executable).with_name("pdf2epub")
CANARY = "CANARY"


def encrypted_scan(target: Path, password: str) -> Path:
    """The two-page scanned fixture, encrypted with AES-256 under user password
    ``password``."""
    writer = PdfWriter(clone_from=PdfReader(FIXTURES / "scanned" / "two-pages.pdf"))
    writer.encrypt(user_password=password, algorithm="AES-256")
    with target.open("wb") as out:
        writer.write(out)
    return target


@pytest.mark.ac("PWD-AC21")
def test_the_password_reaches_neither_tesseract_nor_the_worker(tmp_path: Path) -> None:
    book = encrypted_scan(tmp_path / "book.pdf", CANARY)
    calls = tmp_path / "tesseract.jsonl"
    started = tmp_path / "worker.json"
    program = fake_tesseract(tmp_path / "bin", record(calls))
    env = worker_hooks.environment({book.name: {"action": "record", "path": str(started)}})
    env["PDF2EPUB_PASSWORD"] = CANARY

    run = subprocess.run(
        [str(PDF2EPUB), "--json", "--tesseract", str(program), str(book)],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )

    assert run.returncode == 0, run.stderr
    [finished] = [
        event
        for line in run.stdout.splitlines()
        if (event := json.loads(line))["type"] == "conversion_finished"
    ]
    assert finished["outcome"] == "converted"
    assert finished["password_source"] == "env"
    tesseract_runs = [json.loads(line) for line in calls.read_text(encoding="utf-8").splitlines()]
    assert len(tesseract_runs) == 2, "the scanned pages were not OCR'd"
    worker = json.loads(started.read_text(encoding="utf-8"))
    for process in [*tesseract_runs, worker]:
        recorded = json.dumps([process["argv"], process["env"]])
        assert CANARY not in recorded
        assert "PDF2EPUB_PASSWORD" not in recorded
