"""Page-break markers and the page list, read back from the written EPUB (RFL-R25,
EPUB-R5, EPUB-R19).

Every ``epub:type="pagebreak"`` span in the spine is a ``PageBreak`` of the document model.
Expected labels come from the fixtures' page-label number trees (see
``fixturegen/pagenumbers.py``), not from pdf2epub.
"""

import zipfile
from pathlib import Path

import pytest
from conftest import FIXTURES, convert_copy
from lxml import etree

XHTML = "{http://www.w3.org/1999/xhtml}"
EPUB_TYPE = "{http://www.idpf.org/2007/ops}type"
OPF_NS = {"opf": "http://www.idpf.org/2007/opf"}

PAGE_LABELS = FIXTURES / "born-digital" / "page-labels.pdf"
ODD_LABELS = FIXTURES / "born-digital" / "odd-page-labels.pdf"
NO_LABELS = FIXTURES / "scanned" / "page-numbers-missing.pdf"


def page_breaks(epub: Path) -> list[tuple[str, str, str]]:
    """Every page-break span in spine order: (file, id, aria-label, as parsed)."""
    found: list[tuple[str, str, str]] = []
    with zipfile.ZipFile(epub) as archive:
        opf = etree.fromstring(archive.read("OEBPS/content.opf"))
        items = {
            item.get("id"): item.get("href")
            for item in opf.findall("opf:manifest/opf:item", OPF_NS)
        }
        for ref in opf.findall("opf:spine/opf:itemref", OPF_NS):
            name = str(items[ref.get("idref")])
            for element in etree.fromstring(archive.read(f"OEBPS/{name}")).iter():
                if element.get(EPUB_TYPE) == "pagebreak":
                    found.append((name, str(element.get("id")), str(element.get("aria-label"))))
    return found


def page_list(epub: Path) -> list[tuple[str, str]]:
    """The nav document's page-list entries: (href, label)."""
    with zipfile.ZipFile(epub) as archive:
        nav = etree.fromstring(archive.read("OEBPS/nav.xhtml"))
    [pages] = [n for n in nav.iter(f"{XHTML}nav") if n.get(EPUB_TYPE) == "page-list"]
    return [
        (str(a.get("href")), "".join(str(t) for t in a.itertext())) for a in pages.iter(f"{XHTML}a")
    ]


@pytest.mark.ac("RFL-AC17")
def test_page_labels_become_page_break_markers_in_order(tmp_path: Path) -> None:
    epub = convert_copy(PAGE_LABELS, tmp_path)

    labels = [label for _, _, label in page_breaks(epub)]
    assert labels == ["i", "ii", "iii", "iv", *(str(n) for n in range(1, 21))]


@pytest.mark.ac("RFL-AC17")
def test_without_page_labels_the_markers_are_numbered_from_one(tmp_path: Path) -> None:
    epub = convert_copy(NO_LABELS, tmp_path)

    labels = [label for _, _, label in page_breaks(epub)]
    assert labels == [str(n) for n in range(1, 31)]


@pytest.mark.ac("EPUB-AC13")
def test_page_break_ids_come_from_page_indexes_whatever_the_labels(tmp_path: Path) -> None:
    epub = convert_copy(ODD_LABELS, tmp_path)

    breaks = page_breaks(epub)
    assert [page_id for _, page_id, _ in breaks] == ["page-1", "page-2", "page-3", "page-4"]
    assert [label for _, _, label in breaks] == ["i", "i", "A&B 1", "<2>"]
    [name] = {name for name, _, _ in breaks}  # one chapter file
    assert page_list(epub) == [
        (f"{name}#page-1", "i"),
        (f"{name}#page-2", "i"),
        (f"{name}#page-3", "A&B 1"),
        (f"{name}#page-4", "<2>"),
    ]
    # epubcheck runs on this EPUB when the test ends (tests/conftest.py) and fails it on
    # any error.
