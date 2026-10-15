"""A scanned page whose text comes from OCR or from a trusted prior OCR layer shows that
text, not also the scan it was read from; its smaller pictures, a born-digital page's
full-page photograph and page-image fallbacks are kept (OCR-R17, RFL-R26).

Conversions run in-process; the fake engine (``fake_engine.py``) stands in for Tesseract.
What each fixture holds comes from its generator: ``fixturegen/textlayers.py``
(``ocr-layer.pdf``, ``half-layer.pdf``), ``fixturegen/scanlayers.py``
(``inset-picture.pdf``), ``fixturegen/scans.py`` (``image-only.pdf``) and
``fixturegen/images.py`` (``full-page-photo.pdf``).
"""

import io
import zipfile
from pathlib import Path

import pytest
from conftest import FIXTURES
from fake_engine import FakeEngine, install, words_of
from lxml import etree
from PIL import Image
from test_routing import SCANNED, XHTML, convert, page_contents, squash, text_of

from pdf2epub import Outcome
from pdf2epub.ocr.engine import OcrLine, OcrPageResult, OcrRequest, Word

OCR_LAYER = SCANNED / "ocr-layer.pdf"
INSET_PICTURE = SCANNED / "inset-picture.pdf"
FULL_PAGE_PHOTO = FIXTURES / "images" / "full-page-photo.pdf"
HALF_LAYER = FIXTURES / "must-reject" / "half-layer.pdf"
INSET_SIZE = (1350, 708)
"""The inset picture's pixels: 324 x 170 pt at 300 DPI (``scanlayers.INSET``)."""
WORDS = ("Harbour.", "Lantern.", "Telegram.")


def one_word(call: int, request: OcrRequest) -> OcrPageResult:
    """The n-th page's word of ``WORDS``, its box holding all the page's ink, so the first
    attempt is accepted (OCR-R19); a different word on each page, so it isn't furniture."""
    width, height = request.image.size
    word = Word(WORDS[call], 0, 0, width, height, 0.95, 95)
    return OcrPageResult(lines=(OcrLine((word,), 60),))


def converted(source: Path, folder: Path, mode: str) -> Path:
    report, _ = convert([(source, "book.pdf")], folder, mode)
    [result] = report.conversions
    assert result.outcome is Outcome.CONVERTED
    assert result.output is not None
    return Path(result.output)


def figures(elements: list[etree._Element]) -> list[etree._Element]:
    return [e for e in elements if e.tag == f"{XHTML}figure"]


def image_size(epub: Path, figure: etree._Element) -> tuple[int, int]:
    [img] = figure.iter(f"{XHTML}img")
    with zipfile.ZipFile(epub) as archive:
        data = archive.read(f"OEBPS/{img.get('src')}")
    return Image.open(io.BytesIO(data)).size


def paragraphs(source: Path) -> list[str]:
    return [squash(p) for p in source.with_suffix(".txt").read_text(encoding="utf-8").split("\n\n")]


@pytest.mark.ac("OCR-AC27")
@pytest.mark.parametrize("mode", ["auto", "never", "always"])
def test_a_page_read_from_its_scan_shows_its_text_and_not_the_scan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    engine = install(monkeypatch, FakeEngine(words_of(OCR_LAYER, 300)))

    epub = converted(OCR_LAYER, tmp_path, mode)

    assert len(engine.requests) == (4 if mode == "always" else 0)  # the layer is trusted
    pages = page_contents(epub)
    assert sorted(pages) == [1, 2, 3, 4]
    for number, elements in pages.items():
        assert figures(elements) == [], f"page {number} keeps its scan"
        assert text_of(elements)
    text = text_of([e for elements in pages.values() for e in elements])
    for paragraph in paragraphs(OCR_LAYER):
        assert paragraph in text


@pytest.mark.ac("OCR-AC27")
def test_a_page_ocred_directly_shows_its_text_and_not_the_scan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = install(monkeypatch, FakeEngine(one_word))

    epub = converted(SCANNED / "image-only.pdf", tmp_path, "auto")

    assert len(engine.requests) == 3
    pages = page_contents(epub)
    assert sorted(pages) == [1, 2, 3]
    for number, elements in pages.items():
        assert figures(elements) == []
        assert text_of(elements) == WORDS[number - 1]


@pytest.mark.ac("OCR-AC27")
@pytest.mark.parametrize("mode", ["auto", "never", "always"])
def test_a_scanned_page_keeps_its_smaller_picture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    install(monkeypatch, FakeEngine(words_of(INSET_PICTURE, 300)))

    epub = converted(INSET_PICTURE, tmp_path, mode)

    [elements] = page_contents(epub).values()
    [figure] = figures(elements)
    assert image_size(epub, figure) == INSET_SIZE
    text = text_of(elements)
    above, below = paragraphs(INSET_PICTURE)
    assert above in text
    assert below in text


@pytest.mark.ac("OCR-AC27")
def test_a_born_digital_page_keeps_the_photograph_that_fills_it(tmp_path: Path) -> None:
    epub = converted(FULL_PAGE_PHOTO, tmp_path, "auto")

    [elements] = page_contents(epub).values()
    [figure] = figures(elements)
    assert image_size(epub, figure)[1] == 1600  # downscaled from 1200 x 1800 (RFL-R27)
    [caption] = paragraphs(FULL_PAGE_PHOTO)
    assert caption in text_of(elements)


@pytest.mark.ac("OCR-AC27")
def test_a_page_image_fallback_is_unchanged(tmp_path: Path) -> None:
    epub = converted(HALF_LAYER, tmp_path, "never")

    pages = page_contents(epub)
    assert sorted(pages) == [1, 2, 3, 4]
    for elements in pages.values():
        [figure] = elements
        assert figure.tag == f"{XHTML}figure"
        assert "page-image" in str(figure.get("class"))
