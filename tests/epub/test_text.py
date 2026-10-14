"""The book's text as read back from the written EPUB: normalisation, furniture removal,
page joins and de-hyphenation (RFL-R8, RFL-R16, RFL-R17, RFL-R18, RFL-R19).

Each ``<p>`` in the spine is one ``Paragraph`` of the document model, and each
``epub:type="pagebreak"`` span is a ``PageBreak``: inside a ``<p>`` it is an inline,
outside one it is a block. Expected text comes from the fixtures' ground truth.
"""

import re
import shutil
import unicodedata
import zipfile
from dataclasses import dataclass
from pathlib import Path

import pytest
from conftest import FIXTURES, NOVEL, RecordingSink
from lxml import etree

from pdf2epub import (
    BatchOptions,
    ConversionOptions,
    ConversionResult,
    DiscoveryOptions,
    InputSpec,
    Outcome,
    Severity,
    plan_batch,
    run_batch,
)

TYPOGRAPHY = FIXTURES / "born-digital" / "typography.pdf"
XHTML = "{http://www.w3.org/1999/xhtml}"
EPUB_TYPE = "{http://www.idpf.org/2007/ops}type"
OPF_NS = {"opf": "http://www.idpf.org/2007/opf"}
HEADINGS = {f"{XHTML}h{n}" for n in range(1, 7)}


@dataclass(frozen=True)
class Marker:
    """A page-break marker: its label, and whether it sits inside a paragraph."""

    label: str
    inline: bool


@dataclass(frozen=True)
class Para:
    """A paragraph (or heading) read back from the EPUB."""

    tag: str
    text: str
    breaks: list[tuple[int, str]]
    """Inline page breaks: (offset into ``text``, label)."""


@dataclass(frozen=True)
class Book:
    blocks: list[Para]
    markers: list[Marker]
    text: str
    """Every XHTML content document in the spine, concatenated."""

    @property
    def paragraphs(self) -> list[str]:
        return [b.text for b in self.blocks if b.tag == f"{XHTML}p"]


def convert(
    source: Path, tmp_path: Path, options: ConversionOptions | None = None
) -> tuple[ConversionResult, Path]:
    pdf = tmp_path / source.name
    shutil.copyfile(source, pdf)
    plan = plan_batch([InputSpec(pdf)], DiscoveryOptions())
    report = run_batch(
        plan, BatchOptions(isolation="inprocess"), options or ConversionOptions(), RecordingSink()
    )
    [result] = report.conversions
    assert result.outcome is Outcome.CONVERTED, result.issues
    assert result.output is not None
    return result, Path(result.output)


def read_book(epub: Path) -> Book:
    blocks: list[Para] = []
    markers: list[Marker] = []
    texts: list[str] = []
    with zipfile.ZipFile(epub) as archive:
        opf_path = "OEBPS/content.opf"
        opf = etree.fromstring(archive.read(opf_path))
        items = {
            item.get("id"): item.get("href")
            for item in opf.findall("opf:manifest/opf:item", OPF_NS)
        }
        for ref in opf.findall("opf:spine/opf:itemref", OPF_NS):
            raw = archive.read(f"OEBPS/{items[ref.get('idref')]}")
            texts.append(raw.decode("utf-8"))
            body = etree.fromstring(raw).find(f"{XHTML}body")
            assert body is not None
            for element in body.iter():
                if element.get(EPUB_TYPE) == "pagebreak":
                    inline = element.getparent() is not body
                    markers.append(Marker(str(element.get("aria-label")), inline))
                if element.tag == f"{XHTML}p" or element.tag in HEADINGS:
                    blocks.append(_para(element))
    return Book(blocks, markers, "\n".join(texts))


def _para(element: etree._Element) -> Para:
    parts: list[str] = []
    breaks: list[tuple[int, str]] = []

    def walk(node: etree._Element) -> None:
        if node.get(EPUB_TYPE) == "pagebreak":
            breaks.append((len("".join(parts)), str(node.get("aria-label"))))
        parts.append(node.text or "")
        for child in node:
            walk(child)
            parts.append(child.tail or "")

    walk(element)
    return Para(str(element.tag), "".join(parts), breaks)


def ground_truth(pdf: Path) -> list[str]:
    """The fixture's ground truth: one entry per paragraph or title."""
    text = pdf.with_suffix(".txt").read_text(encoding="utf-8")
    return [block.strip() for block in text.split("\n\n") if block.strip()]


def novel_titles() -> set[str]:
    # In the novel's ground truth, chapter and section titles are the only entries that
    # don't end with a full stop.
    return {entry for entry in ground_truth(NOVEL) if not entry.endswith(".")}


@pytest.mark.ac("RFL-AC1")
def test_novel_body_paragraphs_come_out_whole_and_in_order(tmp_path: Path) -> None:
    result, epub = convert(NOVEL, tmp_path)

    serious = {Severity.ERROR, Severity.WARNING}
    assert [i for i in result.issues if i.severity in serious] == []
    truth = ground_truth(NOVEL)
    titles = novel_titles()
    body = [entry for entry in truth if entry not in titles]
    assert len(body) > 100  # the ground truth really holds the novel's paragraphs
    paragraphs = read_book(epub).paragraphs
    assert [p for p in paragraphs if p not in titles] == body


@pytest.mark.ac("RFL-AC10")
def test_running_headers_and_page_numbers_are_removed(tmp_path: Path) -> None:
    _, epub = convert(NOVEL, tmp_path)
    blocks = read_book(epub).blocks

    # The book title runs on even pages and nowhere else in the text.
    assert [b.text for b in blocks if "The Lantern Coast" in b.text] == []
    # Each chapter title runs on odd pages, but only its chapter opener should remain.
    for title in novel_titles():
        assert [b.text for b in blocks if title in b.text] == [title]
    # No block is a bare page number, and none starts or ends with one.
    assert [b.text for b in blocks if re.fullmatch(r"\W*\d+\W*", b.text)] == []
    assert [b.text for b in blocks if re.search(r"(^\d+\s|\s\d+$)", b.text)] == []


@pytest.mark.ac("RFL-AC12")
def test_sentence_across_a_page_break_is_one_paragraph_with_an_inline_break(
    tmp_path: Path,
) -> None:
    _, epub = convert(NOVEL, tmp_path)
    book = read_book(epub)

    # Page 1 ends "...recognised the distant staircase as the" and page 2 continues
    # "boats came home." without an indent (checked by hand against the fixture).
    [joined] = [b for b in book.blocks if "the distant staircase as the boats came home" in b.text]
    [(offset, label)] = joined.breaks
    assert label == "2"
    assert joined.text[:offset].endswith("staircase as the ")
    assert joined.text[offset:].startswith("boats came home.")
    # Every page still has exactly one marker, in page order.
    assert [m.label for m in book.markers] == [str(n) for n in range(1, 41)]
    assert Marker("2", inline=True) in book.markers


@pytest.mark.ac("RFL-AC12")
def test_paragraph_ending_a_page_with_a_full_stop_is_not_joined(tmp_path: Path) -> None:
    _, epub = convert(NOVEL, tmp_path)
    book = read_book(epub)

    # Page 2 ends "...and then eventually went home." and page 3 opens with an indented
    # paragraph "Everyone particularly carried the heavy lantern ...".
    texts = book.paragraphs
    [end] = [
        i
        for i, t in enumerate(texts)
        if t.endswith("quiet station, and then eventually went home.")
    ]
    assert texts[end + 1].startswith("Everyone particularly carried the heavy lantern")
    assert Marker("3", inline=False) in book.markers


@pytest.mark.ac("RFL-AC7")
def test_ligatures_expanded_text_is_nfc_and_soft_hyphens_are_gone(tmp_path: Path) -> None:
    _, epub = convert(TYPOGRAPHY, tmp_path)
    book = read_book(epub)

    [paragraph] = book.paragraphs
    assert "The first floor of the old caf\u00e9 held" in paragraph
    assert "caf\u00e9" in paragraph and "cafe\u0301" not in paragraph
    assert "something unusual" in paragraph
    assert unicodedata.is_normalized("NFC", book.text)
    assert "\u00ad" not in book.text
    assert re.search("[\ufb00-\ufb06]", book.text) is None


@pytest.mark.ac("RFL-AC11")
def test_dehyphenation_with_the_english_wordlist(tmp_path: Path) -> None:
    _, epub = convert(TYPOGRAPHY, tmp_path)

    [paragraph] = read_book(epub).paragraphs
    assert paragraph == ground_truth(TYPOGRAPHY)[0]
    assert "example" in paragraph
    assert "well-known" in paragraph
    assert "information" in paragraph


@pytest.mark.ac("RFL-AC11")
def test_without_a_wordlist_only_the_soft_hyphen_word_is_joined(tmp_path: Path) -> None:
    # German has no wordlist in pdf2epub.
    _, epub = convert(TYPOGRAPHY, tmp_path, ConversionOptions(language="de"))

    [paragraph] = read_book(epub).paragraphs
    assert "exam-ple" in paragraph and "example" not in paragraph
    assert "well-known" in paragraph
    assert "information" in paragraph
