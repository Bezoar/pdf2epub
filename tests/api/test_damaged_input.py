"""Damaged and hostile PDFs fail cleanly or convert with a warning (RFL-R2 to RFL-R6,
RFL-R35), driven through ``plan_batch`` / ``run_batch`` in-process."""

import os
import resource
import shutil
import socket
import subprocess
import sys
import webbrowser
from pathlib import Path
from typing import Any

import pytest
from conftest import FIXTURES, NOVEL, RecordingSink

from pdf2epub import (
    BatchOptions,
    BatchReport,
    ConversionOptions,
    DiscoveryOptions,
    InputSpec,
    OcrOptions,
    plan_batch,
    run_batch,
)

DAMAGED = FIXTURES / "damaged"
TRUNCATED = DAMAGED / "truncated.pdf"
NO_XREF = DAMAGED / "novel-no-xref.pdf"
ZERO_PAGES = DAMAGED / "zero-pages.pdf"
IMAGE_BOMB = DAMAGED / "image-bomb.pdf"
STREAM_BOMB = DAMAGED / "stream-bomb.pdf"
HOSTILE = FIXTURES / "hostile" / "actions.pdf"
BLANK = FIXTURES / "born-digital" / "blank-pages.pdf"
BLANK_PLUS_TEXT = FIXTURES / "born-digital" / "blank-pages-plus-text.pdf"

GIGABYTE = 1 << 30


def convert(
    sources: list[Path],
    folder: Path,
    sink: RecordingSink,
    options: ConversionOptions | None = None,
) -> BatchReport:
    """Copy ``sources`` into ``folder`` and convert them as one in-process batch."""
    copies = []
    for source in sources:
        copy = folder / source.name
        shutil.copyfile(source, copy)
        copies.append(InputSpec(copy))
    plan = plan_batch(copies, DiscoveryOptions())
    return run_batch(
        plan, BatchOptions(isolation="inprocess"), options or ConversionOptions(), sink
    )


def codes(issues: list[dict[str, Any]]) -> list[str]:
    return [issue["code"] for issue in issues]


def finished(sink: RecordingSink) -> list[dict[str, Any]]:
    return sink.of_type("conversion_finished")


@pytest.mark.ac("RFL-AC2")
def test_truncated_pdf_fails_corrupt_and_writes_no_epub(
    tmp_path: Path, sink: RecordingSink
) -> None:
    report = convert([TRUNCATED], tmp_path, sink)

    [result] = finished(sink)
    assert result["outcome"] == "failed"
    assert codes(result["issues"]) == ["corrupt_pdf"]
    assert result["issues"][0]["severity"] == "error"
    assert result["output"] is None
    assert not (tmp_path / "truncated.epub").exists()
    assert list(tmp_path.glob("*.epub")) == []
    assert report.exit_code == 1


@pytest.mark.ac("RFL-AC3")
def test_pdf_without_its_cross_reference_table_converts_with_repaired_warning(
    tmp_path: Path, sink: RecordingSink
) -> None:
    convert([NO_XREF], tmp_path, sink)

    [result] = finished(sink)
    assert result["outcome"] == "converted"
    [repaired] = [i for i in result["issues"] if i["code"] == "repaired_pdf"]
    assert repaired["severity"] == "warning"
    assert (tmp_path / "novel-no-xref.epub").is_file()
    assert result["pages"] == 40


def test_intact_pdf_has_no_repaired_warning(tmp_path: Path, sink: RecordingSink) -> None:
    # The other half of RFL-R3: the warning is about damage, not about every file.
    convert([NOVEL], tmp_path, sink)

    [result] = finished(sink)
    assert result["outcome"] == "converted"
    assert "repaired_pdf" not in codes(result["issues"])


@pytest.mark.ac("RFL-AC4")
def test_zero_page_pdf_fails_empty_document(tmp_path: Path, sink: RecordingSink) -> None:
    convert([ZERO_PAGES], tmp_path, sink)

    [result] = finished(sink)
    assert result["outcome"] == "failed"
    assert codes(result["issues"]) == ["empty_document"]
    assert result["issues"][0]["severity"] == "error"
    assert result["output"] is None
    assert list(tmp_path.glob("*.epub")) == []


@pytest.mark.ac("RFL-AC6")
def test_image_bomb_fails_resource_limit_and_the_rest_of_the_batch_converts(
    tmp_path: Path, sink: RecordingSink
) -> None:
    report = convert([IMAGE_BOMB, NOVEL], tmp_path, sink)

    bomb, novel = finished(sink)
    assert bomb["outcome"] == "failed"
    assert codes(bomb["issues"]) == ["resource_limit"]
    [limit] = bomb["issues"]
    assert limit["severity"] == "error"
    assert limit["pages"] == [1]
    assert "pixel" in limit["message"]
    assert "page 1" in limit["message"]
    assert not (tmp_path / "image-bomb.epub").exists()
    assert novel["outcome"] == "converted"
    assert (tmp_path / "novel.epub").is_file()
    assert report.totals.failed == 1 and report.totals.converted == 1
    # Decoding the bomb would take 1.6 GB; ru_maxrss is in bytes on macOS, KiB on Linux.
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    peak_bytes = peak if sys.platform == "darwin" else peak * 1024
    assert peak_bytes < GIGABYTE


def test_content_stream_bomb_fails_resource_limit(tmp_path: Path, sink: RecordingSink) -> None:
    # RFL-R6's other limit: a content stream that inflates to 1 GiB.
    convert([STREAM_BOMB], tmp_path, sink)

    [result] = finished(sink)
    assert result["outcome"] == "failed"
    assert codes(result["issues"]) == ["resource_limit"]
    [limit] = result["issues"]
    assert limit["pages"] == [1]
    assert "decompressed stream size" in limit["message"]
    assert list(tmp_path.glob("*.epub")) == []


class Tripwire:
    """Records every attempt to reach the network or start a program, and blocks it."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.attempts: list[str] = []

        def blocked(name: str) -> Any:
            def record(*args: Any, **kwargs: Any) -> Any:
                self.attempts.append(f"{name}{args[1:] if name.startswith('socket.') else args}")
                raise RuntimeError(f"{name} is blocked in this test")

            return record

        for name in ("connect", "connect_ex", "sendto", "sendmsg"):
            monkeypatch.setattr(socket.socket, name, blocked(f"socket.{name}"))
        monkeypatch.setattr(socket, "getaddrinfo", blocked("getaddrinfo"))
        monkeypatch.setattr(socket, "gethostbyname", blocked("gethostbyname"))
        monkeypatch.setattr(subprocess.Popen, "__init__", blocked("Popen"))
        monkeypatch.setattr(os, "system", blocked("os.system"))
        monkeypatch.setattr(os, "posix_spawn", blocked("os.posix_spawn"))
        monkeypatch.setattr(os, "execv", blocked("os.execv"))
        monkeypatch.setattr(webbrowser, "open", blocked("webbrowser.open"))


@pytest.mark.ac("RFL-AC5")
def test_javascript_actions_and_external_references_never_run_or_fetch(
    tmp_path: Path, sink: RecordingSink, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The fixture's launch action names launched.sh beside the PDF: make it leave a mark.
    marker = tmp_path / "launched"
    script = tmp_path / "launched.sh"
    script.write_text(f"#!/bin/sh\ntouch '{marker}'\n")
    script.chmod(0o755)
    tripwire = Tripwire(monkeypatch)
    # The run's preflight probes Tesseract (OCR-R24) by running it; with no Tesseract
    # there, any program started can only have come from the PDF.
    no_tesseract = OcrOptions(tesseract_path=tmp_path / "no-tesseract")

    convert([HOSTILE], tmp_path, sink, ConversionOptions(ocr=no_tesseract))

    assert tripwire.attempts == []
    assert not marker.exists()
    [result] = finished(sink)
    assert result["outcome"] == "converted"
    assert (tmp_path / "actions.epub").is_file()


@pytest.mark.ac("RFL-AC24")
@pytest.mark.parametrize("mode", ["auto", "always", "never"])
def test_all_blank_pdf_fails_empty_document_without_ocr(
    tmp_path: Path, sink: RecordingSink, mode: str
) -> None:
    options = ConversionOptions(ocr=OcrOptions(mode=mode))  # type: ignore[arg-type]  # parametrised Literal
    convert([BLANK], tmp_path, sink, options)

    [result] = finished(sink)
    assert result["outcome"] == "failed"
    assert codes(result["issues"]) == ["empty_document"]
    assert result["issues"][0]["severity"] == "error"
    assert result["output"] is None
    assert list(tmp_path.glob("*.epub")) == []
    # The OCR engine was never called: no ocr stage, no OCR summary (API-R13, API-R21).
    assert result["ocr"] is None
    assert [e for e in sink.of_type("progress") if e["stage"] == "ocr"] == []


@pytest.mark.ac("RFL-AC24")
def test_blank_pages_beside_a_text_page_convert_without_issues_for_them(
    tmp_path: Path, sink: RecordingSink
) -> None:
    convert([BLANK_PLUS_TEXT], tmp_path, sink)

    [result] = finished(sink)
    assert result["outcome"] == "converted"
    assert result["pages"] == 4
    assert [i for i in result["issues"] if set(i["pages"]) & {1, 2, 3}] == []
    assert "empty_document" not in codes(result["issues"])
