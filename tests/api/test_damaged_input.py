"""Damaged and hostile PDFs fail cleanly or convert with a warning (RFL-R2 to RFL-R6,
RFL-R35, RFL-R37), driven through ``plan_batch`` / ``run_batch`` in-process."""

import os
import re
import resource
import shutil
import socket
import subprocess
import sys
import webbrowser
import zipfile
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


# --- Damage that once crashed a conversion (#94) ----------------------------------------

TWO_PAGES = FIXTURES / "born-digital" / "two-pages.pdf"
UPDATES = 1500
"""More incremental updates than Python's default recursion limit (1000) has frames."""


def with_empty_updates(source: Path, target: Path, count: int) -> None:
    """Write ``source`` followed by ``count`` incremental updates that change nothing,
    each naming the one before as ``/Prev``."""
    data = bytearray(source.read_bytes())
    tail = bytes(data[data.rindex(b"trailer") :])
    size = re.search(rb"/Size (\d+)", tail)
    root = re.search(rb"/Root (\d+ \d+ R)", tail)
    previous = re.search(rb"startxref\s+(\d+)", tail)
    assert size and root and previous, "the source's trailer is not as expected"
    offset = int(previous[1])
    for _ in range(count):
        section = len(data)
        data += b"xref\n0 1\n0000000000 65535 f \ntrailer\n"
        data += b"<< /Size %s /Root %s /Prev %d >>\n" % (size[1], root[1], offset)
        data += b"startxref\n%d\n%%%%EOF\n" % section
        offset = section
    target.write_bytes(bytes(data))


def book_text(epub: Path) -> str:
    """Every word in the book's XHTML documents, markup removed."""
    with zipfile.ZipFile(epub) as book:
        pages = [book.read(name).decode() for name in book.namelist() if name.endswith(".xhtml")]
    return " ".join(re.sub(r"<[^>]+>", " ", page) for page in pages)


@pytest.mark.ac("RFL-AC29")
@pytest.mark.parametrize("isolation", ["inprocess", "subprocess"])
def test_damage_that_loops_or_disagrees_fails_cleanly_or_converts_repaired(
    tmp_path: Path, sink: RecordingSink, isolation: str
) -> None:
    sources = [
        DAMAGED / "stale-xref.pdf",
        DAMAGED / "unmatched-pages.pdf",
        DAMAGED / "missing-page.pdf",
        DAMAGED / "xref-loop.pdf",
        DAMAGED / "objstm-loop.pdf",
        DAMAGED / "objstm-root-loop.pdf",
    ]
    inputs = []
    for source in sources:
        shutil.copyfile(source, tmp_path / source.name)
        inputs.append(InputSpec(tmp_path / source.name))
    with_empty_updates(TWO_PAGES, tmp_path / "long-chain.pdf", UPDATES)
    inputs.append(InputSpec(tmp_path / "long-chain.pdf"))
    plan = plan_batch(inputs, DiscoveryOptions())
    options = BatchOptions(isolation=isolation)  # type: ignore[arg-type]  # parametrised Literal

    run_batch(plan, options, ConversionOptions(), sink)

    results = {Path(result["source"]).stem: result for result in finished(sink)}
    every_code = [code for result in results.values() for code in codes(result["issues"])]
    assert "internal_error" not in every_code
    for name in ("unmatched-pages", "missing-page", "objstm-loop", "objstm-root-loop"):
        assert results[name]["outcome"] == "failed", name
        assert codes(results[name]["issues"]) == ["corrupt_pdf"], name
        assert not (tmp_path / f"{name}.epub").exists(), name

    for name in ("stale-xref", "xref-loop"):
        assert results[name]["outcome"] == "converted", name
        assert "repaired_pdf" in codes(results[name]["issues"]), name
    stale = book_text(tmp_path / "stale-xref.epub")
    assert "Stale offsets, first page." in stale
    assert "Stale offsets, second page." in stale
    looped = book_text(tmp_path / "xref-loop.epub")
    assert "The final page." in looped
    assert "draft" not in looped

    assert results["long-chain"]["outcome"] == "converted"
    assert results["long-chain"]["pages"] == 2
    assert "repaired_pdf" not in codes(results["long-chain"]["issues"])
