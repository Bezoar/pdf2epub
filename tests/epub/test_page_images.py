"""Page-image fallback (RFL-R11, RFL-R13, RFL-R14, RFL-R15, EPUB-R9, EPUB-R10): pages
set in two columns, and pages with a table or equations, become page images with hidden
searchable text, read back from the written EPUB.

Each page of a converted book is what follows its ``epub:type="pagebreak"`` span: a
``PageImage`` is a ``<figure>`` holding an ``<img>`` and the hidden text; reflowed text is
``<p>`` elements. Expected text comes from the fixtures' ground truth (see
``fixturegen/layouts.py``), never from pdf2epub.
"""

import re
import shutil
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import pytest
from conftest import FIXTURES, RecordingSink
from lxml import etree

from pdf2epub import (
    BatchOptions,
    ConversionOptions,
    DiscoveryOptions,
    InputSpec,
    Outcome,
    plan_batch,
    run_batch,
)

XHTML = "{http://www.w3.org/1999/xhtml}"
EPUB_TYPE = "{http://www.idpf.org/2007/ops}type"
OPF_NS = {"opf": "http://www.idpf.org/2007/opf"}

TWO_COLUMN = FIXTURES / "born-digital" / "two-column.pdf"
COMPLEX_PAGE = FIXTURES / "born-digital" / "complex-page.pdf"


@dataclass
class TruthPage:
    """One page of a fixture's ground truth."""

    kind: str
    paragraphs: list[str] = field(default_factory=list)
    """Prose paragraphs; on a two-column page, the left column's then the right's."""
    columns: dict[str, list[str]] = field(default_factory=dict)
    """A two-column page's paragraphs by side, ``left`` and ``right``."""
    cells: list[str] = field(default_factory=list)
    """A table page's cell texts."""


def ground_truth(pdf: Path) -> dict[int, TruthPage]:
    """The pages of a ``fixturegen/layouts.py`` fixture, by page number."""
    pages: dict[int, TruthPage] = {}
    page: TruthPage | None = None
    section = ""
    for entry in pdf.with_suffix(".txt").read_text(encoding="utf-8").split("\n\n"):
        entry = entry.strip()
        header = re.fullmatch(r"\[page (\d+): ([\w-]+)\]", entry)
        if header:
            page = pages[int(header[1])] = TruthPage(header[2])
            section = ""
            continue
        assert page is not None
        if entry in ("[left]", "[right]", "[table]", "[equation]", "[equations]"):
            section = entry.strip("[]")
        elif section == "table":
            page.cells = [c.strip() for row in entry.splitlines() for c in row.split("|")]
        elif section in ("equation", "equations"):
            pass
        else:
            page.paragraphs.append(entry)
            if section in ("left", "right"):
                page.columns.setdefault(section, []).append(entry)
    return pages


@dataclass
class ReadPage:
    """What a converted book shows for one PDF page."""

    paragraphs: list[str] = field(default_factory=list)
    figures: list[etree._Element] = field(default_factory=list)


def squash(text: str) -> str:
    return " ".join(text.split())


def read_pages(epub: Path) -> dict[int, ReadPage]:
    """Each page's paragraphs and figures, in spine order. A paragraph runs on to the
    page it started on."""
    pages: dict[int, ReadPage] = {}
    with zipfile.ZipFile(epub) as archive:
        opf = etree.fromstring(archive.read("OEBPS/content.opf"))
        items = {
            item.get("id"): item.get("href")
            for item in opf.findall("opf:manifest/opf:item", OPF_NS)
        }
        current: ReadPage | None = None
        for ref in opf.findall("opf:spine/opf:itemref", OPF_NS):
            body = etree.fromstring(archive.read(f"OEBPS/{items[ref.get('idref')]}")).find(
                f"{XHTML}body"
            )
            assert body is not None
            for element in body:
                if element.get(EPUB_TYPE) == "pagebreak":
                    number = int(str(element.get("id")).removeprefix("page-"))
                    current = pages.setdefault(number, ReadPage())
                elif current is None:
                    continue
                elif element.tag == f"{XHTML}figure":
                    current.figures.append(element)
                elif element.tag == f"{XHTML}p":
                    current.paragraphs.append(squash("".join(map(str, element.itertext()))))
    return pages


def hidden_text(figure: etree._Element) -> str:
    """The figure's text outside its image: the page's hidden searchable text."""
    return squash("".join(map(str, figure.itertext())))


def convert(
    source: Path, folder: Path, mode: Literal["auto", "reflow"] = "auto"
) -> tuple[Path, list[dict[str, object]]]:
    """Convert a copy of ``source`` in ``mode``; return the EPUB and the final issues."""
    pdf = folder / source.name
    shutil.copyfile(source, pdf)
    sink = RecordingSink()
    plan = plan_batch([InputSpec(pdf)], DiscoveryOptions())
    report = run_batch(
        plan, BatchOptions(isolation="inprocess"), ConversionOptions(mode=mode), sink
    )
    [result] = report.conversions
    assert result.outcome is Outcome.CONVERTED, result.issues
    assert result.output is not None
    [finished] = sink.of_type("conversion_finished")
    return Path(result.output), finished["issues"]


def fallbacks(issues: list[dict[str, object]]) -> dict[object, object]:
    """The pages of each ``page_fallback`` issue, by reason."""
    return {i["reason"]: i["pages"] for i in issues if i["code"] == "page_fallback"}


@pytest.mark.ac("RFL-AC8")
@pytest.mark.ac("MAIN-AC-B")
@pytest.mark.parametrize("mode", ["auto", "reflow"])
def test_two_column_pages_fall_back_with_column_ordered_text(
    tmp_path: Path, mode: Literal["auto", "reflow"]
) -> None:
    truth = ground_truth(TWO_COLUMN)
    two_column = sorted(n for n, page in truth.items() if page.kind == "two-column")
    assert two_column == [2, 3, 4]

    epub, issues = convert(TWO_COLUMN, tmp_path, mode)

    assert fallbacks(issues) == {"multi_column": two_column}
    pages = read_pages(epub)
    for number in two_column:
        [figure] = pages[number].figures
        assert pages[number].paragraphs == []
        text = hidden_text(figure)
        left, right = (squash(" ".join(truth[number].columns[side])) for side in ("left", "right"))
        # The whole left column, then the whole right column: never interleaved.
        assert left in text
        assert right in text
        assert text.index(left) + len(left) <= text.index(right)
    # The single-column page reflows, in reading order.
    assert pages[1].figures == []
    assert pages[1].paragraphs == truth[1].paragraphs


@pytest.mark.ac("RFL-AC8")
@pytest.mark.ac("MAIN-AC-B")
def test_no_paragraph_holds_text_from_both_columns(tmp_path: Path) -> None:
    truth = ground_truth(TWO_COLUMN)
    epub, _ = convert(TWO_COLUMN, tmp_path)

    # Every column, and every single-column page, is one source of text.
    sources = [
        squash(" ".join(page.columns[side])) for page in truth.values() for side in page.columns
    ] + [squash(" ".join(page.paragraphs)) for page in truth.values() if not page.columns]
    paragraphs = [p for page in read_pages(epub).values() for p in page.paragraphs]
    assert paragraphs
    for paragraph in paragraphs:
        sentences = [s for s in paragraph.split(". ") if s]
        assert any(all(s in source for s in sentences) for source in sources), paragraph


@pytest.mark.ac("RFL-AC9")
def test_a_table_and_math_page_falls_back_as_complex_in_auto_mode(tmp_path: Path) -> None:
    truth = ground_truth(COMPLEX_PAGE)
    assert [n for n, page in truth.items() if page.kind == "table"] == [2]

    epub, issues = convert(COMPLEX_PAGE, tmp_path)

    assert fallbacks(issues) == {"complex": [2]}
    pages = read_pages(epub)
    [figure] = pages[2].figures
    text = hidden_text(figure)
    for cell in truth[2].cells:
        assert cell in text
    for number in (1, 3):
        assert pages[number].figures == []
        assert pages[number].paragraphs == truth[number].paragraphs


@pytest.mark.ac("RFL-AC9")
def test_reflow_mode_keeps_the_complex_page_as_text(tmp_path: Path) -> None:
    truth = ground_truth(COMPLEX_PAGE)

    epub, issues = convert(COMPLEX_PAGE, tmp_path, mode="reflow")

    assert "complex" not in fallbacks(issues)
    pages = read_pages(epub)
    assert pages[2].figures == []
    assert truth[2].paragraphs[0] in pages[2].paragraphs


@pytest.mark.ac("EPUB-AC7")
def test_page_images_are_figures_with_alt_text_and_hidden_text(tmp_path: Path) -> None:
    truth = ground_truth(TWO_COLUMN)
    epub, _ = convert(TWO_COLUMN, tmp_path)

    pages = read_pages(epub)
    with zipfile.ZipFile(epub) as archive:
        packaged = set(archive.namelist())
        for number in (2, 3, 4):
            [figure] = pages[number].figures
            [img] = figure.iter(f"{XHTML}img")
            assert img.get("alt") == f"Page {number}"
            assert f"OEBPS/{img.get('src')}" in packaged
            hidden = [e for e in figure if e.tag != f"{XHTML}img"]
            assert len(hidden) == 1
            # A distinctive sentence from each column is in the hidden element.
            for side in ("left", "right"):
                sentence = truth[number].columns[side][0].split(". ")[1]
                assert sentence in squash("".join(map(str, hidden[0].itertext())))
            assert "hidden" in (hidden[0].get("class") or "")
        stylesheet = archive.read("OEBPS/style.css").decode("utf-8")
    rules = re.sub(r"/\*.*?\*/", "", stylesheet, flags=re.DOTALL)
    assert not re.search(r"font-size\s*:[^;]*\d(px|pt)", rules)
    assert "font-family" not in rules
    assert not re.search(r"(^|[\s;{])(background-)?color\s*:", rules)
    # The hidden text is styled as visually hidden, and the figure as full width.
    assert re.search(r"\.hidden[^{]*\{", rules)
    assert re.search(r"figure[^{]*\{", rules)
