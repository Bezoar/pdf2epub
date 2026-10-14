"""Line blocks (RFL-R36, EPUB-R20): verse and code keep their line breaks.

Converted books are read back from the written EPUB: each ``<p>`` in the spine is a
``Paragraph`` or, with the class ``lines``, a ``LineBlock``, whose lines are the runs of
text between its ``<br/>`` elements; each ``epub:type="pagebreak"`` span directly in the
body is a ``PageBreak`` block. Expected text comes from the fixtures' ground truth. The
writer's own markup is checked by writing a hand-built document model (EPUB-AC14).
"""

import zipfile
from dataclasses import dataclass
from pathlib import Path

import pytest
from conftest import FIXTURES, NOVEL
from conftest import convert_copy as convert
from lxml import etree

from pdf2epub.epub.writer import write_epub
from pdf2epub.reflow.model import (
    Block,
    Chapter,
    Document,
    LineBlock,
    Metadata,
    PageBreak,
    Paragraph,
    Text,
    TocEntry,
)

VERSE = FIXTURES / "born-digital" / "verse-and-code.pdf"
XHTML = "{http://www.w3.org/1999/xhtml}"
EPUB_TYPE = "{http://www.idpf.org/2007/ops}type"
OPF_NS = {"opf": "http://www.idpf.org/2007/opf"}


@dataclass(frozen=True)
class ReadBlock:
    """A body-level block read back from the EPUB."""

    kind: str
    """``paragraph``, ``lines``, ``code`` (a monospace line block) or ``pagebreak``."""
    lines: list[str]
    """A paragraph's text as one entry, or a line block's lines; empty for a page break."""


def chapter_files(epub: Path) -> list[bytes]:
    with zipfile.ZipFile(epub) as archive:
        opf = etree.fromstring(archive.read("OEBPS/content.opf"))
        items = {
            item.get("id"): item.get("href")
            for item in opf.findall("opf:manifest/opf:item", OPF_NS)
        }
        return [
            archive.read(f"OEBPS/{items[ref.get('idref')]}")
            for ref in opf.findall("opf:spine/opf:itemref", OPF_NS)
        ]


def read_blocks(epub: Path) -> list[ReadBlock]:
    blocks: list[ReadBlock] = []
    for raw in chapter_files(epub):
        body = etree.fromstring(raw).find(f"{XHTML}body")
        assert body is not None
        for element in body:
            if element.get(EPUB_TYPE) == "pagebreak":
                blocks.append(ReadBlock("pagebreak", []))
            elif element.tag == f"{XHTML}p":
                classes = (element.get("class") or "").split()
                if "lines" in classes:
                    kind = "code" if "code" in classes else "lines"
                    blocks.append(ReadBlock(kind, _lines(element)))
                else:
                    blocks.append(ReadBlock("paragraph", ["".join(map(str, element.itertext()))]))
    return blocks


def _lines(element: etree._Element) -> list[str]:
    """The text between the ``<br/>`` elements of ``element``, in order."""
    lines = [""]

    def walk(node: etree._Element) -> None:
        if node.tag == f"{XHTML}br":
            lines.append("")
        else:
            lines[-1] += node.text or ""
            for child in node:
                walk(child)
                lines[-1] += child.tail or ""

    walk(element)
    return lines


def ground_truth(pdf: Path) -> list[list[str]]:
    """The fixture's ground truth: one entry per block, each a list of its lines."""
    text = pdf.with_suffix(".txt").read_text(encoding="utf-8")
    return [entry.split("\n") for entry in text.rstrip("\n").split("\n\n")]


@pytest.mark.ac("RFL-AC25")
def test_each_stanza_is_one_line_block_between_prose_paragraphs(tmp_path: Path) -> None:
    blocks = [b for b in read_blocks(convert(VERSE, tmp_path)) if b.kind != "pagebreak"]
    truth = ground_truth(VERSE)
    prose_before, *stanzas, prose_after = truth[:5]
    assert len(stanzas) == 3 and all(len(stanza) == 4 for stanza in stanzas)

    assert blocks[:5] == [
        ReadBlock("paragraph", prose_before),
        *(ReadBlock("lines", stanza) for stanza in stanzas),
        ReadBlock("paragraph", prose_after),
    ]
    # The last paragraph, after the code, is an ordinary paragraph too.
    assert blocks[-1] == ReadBlock("paragraph", truth[-1])


@pytest.mark.ac("RFL-AC26")
def test_the_novel_has_no_line_blocks(tmp_path: Path) -> None:
    blocks = read_blocks(convert(NOVEL, tmp_path))

    assert len([b for b in blocks if b.kind == "paragraph"]) > 100
    assert [b for b in blocks if b.kind in ("lines", "code")] == []


@pytest.mark.ac("RFL-AC27")
def test_code_keeps_its_lines_hyphens_and_spaces_and_is_not_joined_across_pages(
    tmp_path: Path,
) -> None:
    blocks = read_blocks(convert(VERSE, tmp_path))
    truth = ground_truth(VERSE)
    code_page_1, code_page_2 = truth[5], truth[6]
    # The ground truth's code really has what the AC is about.
    assert code_page_1[1].endswith("exam-") and code_page_1[-1].endswith("re-")
    assert code_page_2[0].startswith("    # pair") and code_page_2[2].startswith("        ")

    code = [i for i, b in enumerate(blocks) if b.kind == "code"]
    assert [blocks[i] for i in code] == [
        ReadBlock("code", code_page_1),
        ReadBlock("code", code_page_2),
    ]
    # The first part ends page 1, then page 2 starts with a page-break block.
    first, second = code
    assert blocks[first + 1 : second] == [ReadBlock("pagebreak", [])]
    code_text = "\n".join(line for i in code for line in blocks[i].lines)
    assert "examine" not in code_text and "repair" not in code_text


def _model() -> Document:
    metadata = Metadata(
        title="Lines",
        authors=[],
        language="en",
        identifier="urn:uuid:7e0f8a0c-52aa-4c3b-9d52-000000000052",
        modified="2026-01-01T00:00:00Z",
    )
    verse = LineBlock(
        lines=[[Text("one line,")], [Text("a "), Text("second", italic=True)], [Text("a third.")]],
        monospace=False,
    )
    code = LineBlock(
        lines=[[Text("if ready:")], [Text("    go()")], [Text("done()")]], monospace=True
    )
    blocks: list[Block] = [PageBreak("1", 1), Paragraph([Text("Before.")]), verse, code]
    return Document(metadata, [Chapter("Lines", blocks)], [TocEntry("Lines", chapter=0)])


@pytest.mark.ac("EPUB-AC14")
def test_line_blocks_are_written_as_lines_separated_by_br(tmp_path: Path) -> None:
    epub = tmp_path / "lines.epub"
    epub.write_bytes(write_epub(_model()))  # epubcheck runs on it when the test ends

    with zipfile.ZipFile(epub) as archive:
        chapter = etree.fromstring(archive.read("OEBPS/chapter-001.xhtml"))
        css = archive.read("OEBPS/style.css").decode("utf-8")
    [verse, code] = chapter.iterfind(f".//{XHTML}p[@class]")
    assert verse.get("class") == "lines"
    assert code.get("class") == "lines code"
    assert _lines(verse) == ["one line,", "a second", "a third."]
    assert len(verse.findall(f"{XHTML}br")) == 2
    assert verse.find(f"{XHTML}i") is not None

    [inner] = code
    assert inner.tag == f"{XHTML}code"
    assert len(inner.findall(f"{XHTML}br")) == 2
    assert _lines(code) == ["if ready:", "    go()", "done()"]

    rule = css[css.index("p.code") :]
    assert "white-space: pre-wrap" in rule[: rule.index("}")]
    assert "font-family" not in css
