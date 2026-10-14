"""OCR character accuracy against fixture ground truth (TST-R14, TST-R15, TST-R16,
MAIN-AC-G).

Character accuracy is ``1 - CER`` after both texts are normalised the same way
(``character_accuracy``). Each synthetic scan is converted with real Tesseract, the
EPUB's text is split back into pages at its page-break markers, and every page is scored
against that page's own ground truth. The ground truth of a page comes from the fixture's
generator (``fixturegen/novel.py`` lays the novel out line by line, and the scans are
renders of its pages), never from pdf2epub.

Each OCR'd page costs one orientation run and one to four recognition attempts, so only
the first ``PAGES`` pages of each scan are converted: a chapter opener with its title,
and the page after it, which a paragraph crosses onto.
"""

import shutil
import unicodedata
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pytest
from conftest import OCR_ACCURACY
from fixturegen import novel
from lxml import etree
from pypdf import PdfWriter

from pdf2epub import (
    BatchOptions,
    ConversionOptions,
    DiscoveryOptions,
    InputSpec,
    OcrOptions,
    plan_batch,
    run_batch,
)
from pdf2epub.results import ConversionResult

FIXTURES = Path(__file__).resolve().parent
SCANNED = FIXTURES / "scanned"
XHTML = "{http://www.w3.org/1999/xhtml}"
EPUB_TYPE = "{http://www.idpf.org/2007/ops}type"
OPF_NS = {"opf": "http://www.idpf.org/2007/opf"}

PAGES = 2
"""How many pages of each scan are converted and scored."""
CLEAN, DEGRADED = 0.98, 0.95
"""The v1 bars (TST-R15, MAIN-AC-G)."""
SCANS = {
    "novel-clean": CLEAN,
    "novel-noise": DEGRADED,
    "novel-skew": DEGRADED,
    "novel-rotated": DEGRADED,
    "novel-150dpi": DEGRADED,
}
"""Each synthetic scan of the novel, and its bar. Page ``n`` of every one of them is a
render of page ``n`` of ``born-digital/novel.pdf`` (``fixturegen/scans.py``)."""


# --- Character accuracy (TST-R14) --------------------------------------------------------

LIGATURES = str.maketrans(
    {
        "ﬀ": "ff",
        "ﬁ": "fi",
        "ﬂ": "fl",
        "ﬃ": "ffi",
        "ﬄ": "ffl",
        "ﬅ": "st",
        "ﬆ": "st",
    }
)


def normalise(text: str) -> str:
    """Unicode NFC, ligatures expanded, every run of whitespace one space."""
    return " ".join(unicodedata.normalize("NFC", text).translate(LIGATURES).split())


def edit_distance(a: str, b: str) -> int:
    """The Levenshtein distance between ``a`` and ``b``, one row of the table at a time.

    Within a row, deletions and substitutions come from the row above; an insertion
    chain along the row is a running minimum of ``cost[j] - j``, plus ``j``."""
    if not a or not b:
        return max(len(a), len(b))
    target = np.frombuffer(b.encode("utf-32-le"), dtype=np.uint32)
    steps = np.arange(len(b) + 1)
    row = steps.copy()
    for i, char in enumerate(a, start=1):
        above = row
        row = np.empty_like(above)
        row[0] = i
        row[1:] = np.minimum(above[1:] + 1, above[:-1] + (target != ord(char)))
        row = np.minimum.accumulate(row - steps) + steps
    return int(row[-1])


def errors(truth: str, recognised: str) -> tuple[int, int]:
    """The edit distance between the normalised texts, and the normalised truth's length."""
    truth, recognised = normalise(truth), normalise(recognised)
    return edit_distance(truth, recognised), len(truth)


def character_accuracy(truth: str, recognised: str) -> float:
    """``1 - CER``: the edit distance over the length of the ground truth, both normalised
    (TST-R14)."""
    distance, length = errors(truth, recognised)
    return 1 - distance / length


@pytest.mark.ac("TST-AC9")
def test_character_accuracy_is_one_minus_cer_after_normalisation() -> None:
    assert character_accuracy("ﬁne  day\nend", "fine day end") == 1.0
    assert character_accuracy("abcdefghij", "abcdefghiX") == pytest.approx(0.9)


def test_the_edit_distance_counts_insertions_deletions_and_substitutions() -> None:
    assert edit_distance("kitten", "sitting") == 3
    assert edit_distance("flaw", "lawn") == 2
    assert edit_distance("", "abc") == 3
    assert edit_distance("abc", "abc") == 0
    assert edit_distance("abc", "xabcx") == 2


# --- Ground truth and EPUB text, page by page --------------------------------------------


def page_truth() -> dict[int, str]:
    """Each page of ``born-digital/novel.pdf`` as its generator laid it out, without
    furniture: the chapter title on an opener, then the section titles and body lines,
    with each hyphenated line end joined to the line after it. A word hyphenated across a
    page break is split there, without its hyphen, as the page-break marker inside the
    rejoined word splits it in the EPUB."""
    _, pages = novel.build_chapters()
    truth: dict[int, str] = {}
    for number, page in enumerate(pages, start=1):
        text = novel.CHAPTER_TITLES[page.chapter] if page.opener else ""
        for item in page.items:
            if isinstance(item, novel.Section):
                text += " " + item.title
            elif text.endswith("-"):
                text = text.removesuffix("-") + item.text
            else:
                text += " " + item.text
        truth[number] = text.removesuffix("-")
    return truth


BLOCKS = {"p", "div", "figure", "li", "pre", "br", "h1", "h2", "h3", "h4", "h5", "h6"}


@dataclass
class Page:
    """What the EPUB holds for one PDF page."""

    text: str = ""
    image: bool = False
    """The page is a page image (it fell back)."""


def epub_pages(epub: Path) -> dict[int, Page]:
    """The EPUB's text split back into PDF pages at its page-break markers (EPUB-R7), in
    spine order. The visually hidden text of a page image counts as that page's text."""
    pages: dict[int, Page] = {}
    current: list[Page | None] = [None]

    def add(text: str | None) -> None:
        if text and current[0] is not None:
            current[0].text += text

    def walk(element: etree._Element) -> None:
        if not isinstance(element.tag, str):
            add(element.tail)
            return
        name = etree.QName(element).localname
        if element.get(EPUB_TYPE) == "pagebreak":
            current[0] = pages.setdefault(int(str(element.get("id")).removeprefix("page-")), Page())
        elif name == "img" and current[0] is not None:
            current[0].image = True
        if name in BLOCKS:
            add(" ")
        add(element.text)
        for child in element:
            walk(child)
        if name in BLOCKS:
            add(" ")
        add(element.tail)

    with zipfile.ZipFile(epub) as archive:
        opf = etree.fromstring(archive.read("OEBPS/content.opf"))
        items = {i.get("id"): i.get("href") for i in opf.findall("opf:manifest/opf:item", OPF_NS)}
        for ref in opf.findall("opf:spine/opf:itemref", OPF_NS):
            document = etree.fromstring(archive.read(f"OEBPS/{items[ref.get('idref')]}"))
            body = document.find(f"{XHTML}body")
            if body is not None:
                walk(body)
    return pages


def test_the_born_digital_novel_scores_one_on_every_page(tmp_path: Path) -> None:
    # The measurement itself: the novel's own text layer, reflowed, split back into pages,
    # matches each page's ground truth exactly.
    result = convert(FIXTURES / "born-digital" / "novel.pdf", tmp_path, OcrOptions())
    assert result.output is not None
    truth = page_truth()
    pages = epub_pages(Path(result.output))

    assert sorted(pages) == list(range(1, 41))
    scores = {n: character_accuracy(truth[n], pages[n].text) for n in pages}
    assert scores == dict.fromkeys(range(1, 41), 1.0)


# --- The accuracy measurement (TST-R15, TST-R16, MAIN-AC-G) ------------------------------


def first_pages(source: Path, count: int, target: Path) -> Path:
    """A copy of ``source`` cut to its first ``count`` pages."""
    writer = PdfWriter()
    writer.append(source, pages=(0, count))
    with target.open("wb") as stream:
        writer.write(stream)
    return target


def convert(source: Path, folder: Path, ocr: OcrOptions) -> ConversionResult:
    """Convert a copy of ``source`` alone, in-process."""
    copy = folder / source.name
    shutil.copyfile(source, copy)
    plan = plan_batch([InputSpec(copy)], DiscoveryOptions())
    report = run_batch(
        plan, BatchOptions(isolation="inprocess"), ConversionOptions(ocr=ocr), lambda e: None
    )
    [result] = report.conversions
    return result


@dataclass
class Score:
    """One scan's accuracy figures (TST-R15)."""

    accuracy: float
    """Over every scored page: reflowed pages and fallback pages with hidden text."""
    fallback_scored: int
    """Fallback pages with hidden text: scored, and counted separately."""
    fallback_unscored: int
    """Fallback pages with no hidden text (OCR-R31): not scored, only counted."""

    def __str__(self) -> str:
        return (
            f"accuracy {self.accuracy:.4f}; fallback pages scored on hidden text: "
            f"{self.fallback_scored}; fallback pages without text: {self.fallback_unscored}"
        )


def score(pages: dict[int, Page], truth: dict[int, str]) -> Score:
    distance = length = scored = unscored = 0
    for number, page in pages.items():
        if page.image and not normalise(page.text):
            unscored += 1
            continue
        scored += page.image
        page_distance, page_length = errors(truth[number], page.text)
        distance += page_distance
        length += page_length
    return Score(1 - distance / length if length else 0.0, scored, unscored)


def test_fallback_pages_are_scored_on_hidden_text_and_counted_apart() -> None:
    truth = {1: "abcdefghij", 2: "klmnopqrst", 3: "uvwxyz"}
    pages = {
        1: Page("abcdefghiX"),  # reflowed: 1 error in 10
        2: Page("klmnopqrXX", image=True),  # page image with hidden text: 2 errors in 10
        3: Page("  ", image=True),  # page image without text: not scored
    }

    figures = score(pages, truth)

    assert figures.accuracy == pytest.approx(1 - 3 / 20)
    assert (figures.fallback_scored, figures.fallback_unscored) == (1, 1)


@pytest.mark.tesseract
@pytest.mark.ac("TST-AC10")
@pytest.mark.ac("MAIN-AC-G")
@pytest.mark.parametrize("scan", list(SCANS))
def test_ocr_accuracy_meets_the_v1_bar(
    scan: str, tmp_path: Path, record_property: Callable[[str, object], None]
) -> None:
    source = first_pages(SCANNED / f"{scan}.pdf", PAGES, tmp_path / f"{scan}-source.pdf")
    (tmp_path / "out").mkdir()
    result = convert(source, tmp_path / "out", OcrOptions())
    assert result.output is not None
    pages = epub_pages(Path(result.output))
    assert sorted(pages) == list(range(1, PAGES + 1))

    figures = score(pages, page_truth())
    record_property(OCR_ACCURACY, f"{scan}: {figures}")

    assert figures.accuracy >= SCANS[scan], f"{scan}: {figures}"
    # A page whose OCR result was rejected (OCR-R19) is a page image, never reflowed OCR
    # text; every page image is one of them.
    rejected = {
        page
        for issue in result.issues
        if str(issue.code) == "page_fallback" and issue.reason == "ocr_low_confidence"
        for page in issue.pages
    }
    assert rejected == {n for n, page in pages.items() if page.image}


@pytest.mark.ac("MAIN-AC-G")
def test_without_tesseract_every_scan_finishes_with_ocr_unavailable(tmp_path: Path) -> None:
    inputs = [
        InputSpec(first_pages(SCANNED / f"{scan}.pdf", PAGES, tmp_path / f"{scan}.pdf"))
        for scan in SCANS
    ]
    (tmp_path / "out").mkdir()
    plan = plan_batch(inputs, DiscoveryOptions(output=tmp_path / "out"))
    ocr = OcrOptions(tesseract_path=tmp_path / "no-tesseract")
    report = run_batch(
        plan, BatchOptions(isolation="inprocess"), ConversionOptions(ocr=ocr), lambda e: None
    )

    assert len(report.conversions) == len(SCANS)
    for result in report.conversions:
        assert "ocr_unavailable" in [str(issue.code) for issue in result.issues]
