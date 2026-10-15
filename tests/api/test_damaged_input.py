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
    for name in ("missing-page", "objstm-loop", "objstm-root-loop"):
        assert results[name]["outcome"] == "failed", name
        assert codes(results[name]["issues"]) == ["corrupt_pdf"], name
        assert not (tmp_path / f"{name}.epub").exists(), name

    assert results["unmatched-pages"]["outcome"] == "converted"
    assert unreadable_pages(results["unmatched-pages"]) == [2]

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


# --- Unreadable pages among readable ones (#98) ------------------------------------------

NOTICE = "Page {} could not be read from the PDF."


def unreadable_pages(result: dict[str, Any]) -> list[int]:
    """The pages of the conversion's one ``page_unreadable`` warning."""
    [issue] = [i for i in result["issues"] if i["code"] == "page_unreadable"]
    assert issue["severity"] == "warning"
    return list(issue["pages"])


def book_pages(epub: Path) -> list[str]:
    """The labels of the book's page list, in order."""
    with zipfile.ZipFile(epub) as book:
        nav = book.read("OEBPS/nav.xhtml").decode()
    page_list = nav[nav.index('epub:type="page-list"') :]
    page_list = page_list[: page_list.index("</nav>")]
    return re.findall(r"<a [^>]*>([^<]*)</a>", page_list)


@pytest.mark.ac("RFL-AC30")
@pytest.mark.parametrize("isolation", ["inprocess", "subprocess"])
def test_unreadable_pages_are_disclosed_in_the_book(
    tmp_path: Path, sink: RecordingSink, isolation: str
) -> None:
    names = [
        "unloadable-page",
        "untyped-page",
        "unmatched-pages",
        "unloadable-first-page",
        "unparseable-page",
    ]
    inputs = []
    for name in names:
        shutil.copyfile(DAMAGED / f"{name}.pdf", tmp_path / f"{name}.pdf")
        inputs.append(InputSpec(tmp_path / f"{name}.pdf"))
    plan = plan_batch(inputs, DiscoveryOptions())
    options = BatchOptions(isolation=isolation)  # type: ignore[arg-type]  # parametrised Literal

    run_batch(plan, options, ConversionOptions(), sink)

    results = {Path(result["source"]).stem: result for result in finished(sink)}
    for name in names:
        assert results[name]["outcome"] == "converted", name
        expected = [1] if name == "unloadable-first-page" else [2]
        assert unreadable_pages(results[name]) == expected, name
        # API-R21: one analyse event per page of the book, in page order.
        analysed = [
            (event["done"], event["page"])
            for event in sink.of_type("progress")
            if event["id"] == results[name]["id"] and event["stage"] == "analyse"
        ]
        count = results[name]["pages"]
        assert analysed == [(n, n) for n in range(1, count + 1)], name

    # pdfium counts page 2 but can't load it; pdfminer recovered its text.
    assert results["unloadable-page"]["pages"] == 3
    book = tmp_path / "unloadable-page.epub"
    assert book_pages(book) == ["1", "2", "3"]
    text = " ".join(book_text(book).split())
    first, notice = text.index("The first page."), text.index(NOTICE.format(2))
    assert first < notice < text.index("The lost page.") < text.index("The last page.")

    # Only pdfium has page 2: it renders it, as a page image after the notice.
    assert results["untyped-page"]["pages"] == 2
    fallbacks = [i for i in results["untyped-page"]["issues"] if i["code"] == "page_fallback"]
    assert [(i["reason"], i["pages"]) for i in fallbacks] == [("unreadable", [2])]
    book = tmp_path / "untyped-page.epub"
    assert book_pages(book) == ["1", "2"]
    with zipfile.ZipFile(book) as epub:
        markup = "".join(
            epub.read(name).decode() for name in epub.namelist() if name.endswith(".xhtml")
        )
    notice = markup.index(NOTICE.format(2))
    image = markup.index('alt="Page 2"')
    assert markup.index("The typed page.") < notice < image < markup.index("The untyped page.")

    # pdfminer can't parse page 2 (too deep to lay out); pdfium renders it as a page image
    # after the notice, and page 3 is read as usual (#103).
    assert results["unparseable-page"]["pages"] == 3
    fallbacks = [i for i in results["unparseable-page"]["issues"] if i["code"] == "page_fallback"]
    assert [(i["reason"], i["pages"]) for i in fallbacks] == [("unreadable", [2])]
    book = tmp_path / "unparseable-page.epub"
    assert book_pages(book) == ["1", "2", "3"]
    with zipfile.ZipFile(book) as epub:
        markup = "".join(
            epub.read(name).decode() for name in epub.namelist() if name.endswith(".xhtml")
        )
    notice = markup.index(NOTICE.format(2))
    image = markup.index('alt="Page 2"')
    hidden = markup.index("The unparsed page.")
    assert (
        markup.index("The first page.") < notice < image < hidden < markup.index("The last page.")
    )

    # Only pdfminer has page 2 (the page tree read wrongly): its text follows the notice.
    assert results["unmatched-pages"]["pages"] == 2
    text = " ".join(book_text(tmp_path / "unmatched-pages.epub").split())
    assert text.index("The final page.") < text.index(NOTICE.format(2))
    assert "The final page." in text[text.index(NOTICE.format(2)) :]

    # pdfium can't load page 1: the book has no cover rendered from it, and goes on.
    book = tmp_path / "unloadable-first-page.epub"
    with zipfile.ZipFile(book) as epub:
        assert not [name for name in epub.namelist() if "cover" in name]
    text = " ".join(book_text(book).split())
    assert (
        text.index(NOTICE.format(1)) < text.index("The first page.") < text.index("The last page.")
    )
