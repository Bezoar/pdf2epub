"""The book's structure as read back from the written EPUB: headings and inline styling
(RFL-R20, RFL-R22), chapters and the table of contents (RFL-R23, RFL-R24), navigation
(EPUB-R5, EPUB-R6), chapter markup (EPUB-R7, EPUB-R11) and chapter splitting (EPUB-R8).

Expected values come from the fixtures' documented content and ground truth.
"""

import re
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urldefrag

import pytest
from conftest import FIXTURES, NOVEL
from lxml import etree
from test_text import EPUB_TYPE, HEADINGS, OPF_NS, XHTML, Para, _para, convert, ground_truth

BORN_DIGITAL = FIXTURES / "born-digital"
HEADINGS_SAMPLE = BORN_DIGITAL / "headings.pdf"
NO_OUTLINE = BORN_DIGITAL / "novel-no-outline.pdf"
TWO_ENTRY_OUTLINE = BORN_DIGITAL / "novel-two-entry-outline.pdf"
OVERSIZED = BORN_DIGITAL / "oversized.pdf"
NCX = "{http://www.daisy.org/z3986/2005/ncx/}"

# The novel's outline, as its generator documents it: 10 chapter entries, two of which
# (chapters 2 and 7) have one nested entry.
NOVEL_CHAPTERS = [
    "The Harbour",
    "A Letter from the Mainland",
    "Fog",
    "The Keeper's Notebook",
    "Low Tide",
    "The Schoolteacher",
    "Lamps and Mirrors",
    "The Storm",
    "Afterwards",
    "The Last Light",
]
NOVEL_NESTED = {
    "A Letter from the Mainland": "What the Letter Said",
    "Lamps and Mirrors": "The Night Crossing",
}
NUMBERS = ["ONE", "TWO", "THREE", "FOUR", "FIVE", "SIX", "SEVEN", "EIGHT", "NINE", "TEN"]
NUMBERED_CHAPTERS = [f"CHAPTER {n}" for n in NUMBERS]


@dataclass(frozen=True)
class NavEntry:
    label: str
    href: str
    """Relative to the package folder."""
    children: list["NavEntry"]


@dataclass
class Epub:
    archive: zipfile.ZipFile
    spine: list[str]
    """The chapters' documents in spine order (package-relative): the cover page and the
    nav excluded."""

    def xml(self, name: str) -> etree._Element:
        return etree.fromstring(self.archive.read(f"OEBPS/{name}"))

    def nav(self, kind: str) -> etree._Element:
        [nav] = [n for n in self.xml("nav.xhtml").iter(f"{XHTML}nav") if n.get(EPUB_TYPE) == kind]
        return nav

    def toc(self) -> list[NavEntry]:
        def entries(ol: etree._Element | None) -> list[NavEntry]:
            if ol is None:
                return []
            found = []
            for li in ol.findall(f"{XHTML}li"):
                a = li.find(f"{XHTML}a")
                assert a is not None
                found.append(
                    NavEntry(a.text or "", str(a.get("href")), entries(li.find(f"{XHTML}ol")))
                )
            return found

        return entries(self.nav("toc").find(f"{XHTML}ol"))

    def resolves(self, href: str) -> bool:
        path, fragment = urldefrag(href)
        if f"OEBPS/{path}" not in self.archive.namelist():
            return False
        return not fragment or any(e.get("id") == fragment for e in self.xml(path).iter())

    def first_heading(self, name: str) -> etree._Element:
        body = self.xml(name).find(f"{XHTML}body")
        assert body is not None
        heading = next((e for e in body.iter() if e.tag in HEADINGS), None)
        assert heading is not None, f"{name} has no heading"
        return heading


def open_epub(epub: Path) -> Epub:
    archive = zipfile.ZipFile(epub)
    opf = etree.fromstring(archive.read("OEBPS/content.opf"))
    items = {i.get("id"): str(i.get("href")) for i in opf.findall("opf:manifest/opf:item", OPF_NS)}
    spine = [items[r.get("idref")] for r in opf.findall("opf:spine/opf:itemref", OPF_NS)]
    # EPUB-R4: the cover page (if any), then the nav, then the chapters.
    assert "nav.xhtml" in spine, f"the spine has no nav: {spine}"
    return Epub(archive, spine[spine.index("nav.xhtml") + 1 :])


def content_blocks(epub: Epub) -> list[Para]:
    """The paragraphs and headings of the chapters (the navigation document left out)."""
    return [
        _para(element)
        for name in epub.spine
        for element in epub.xml(name).iter()
        if element.tag == f"{XHTML}p" or element.tag in HEADINGS
    ]


def text_of(element: etree._Element) -> str:
    return " ".join("".join(str(t) for t in element.itertext()).split())


@pytest.mark.ac("RFL-AC15")
def test_chapters_come_from_top_level_outline_entries_with_nested_toc_links(
    tmp_path: Path,
) -> None:
    _, path = convert(NOVEL, tmp_path)
    epub = open_epub(path)

    # 10 chapters, no front matter (the first entry points to page 1): one file each.
    assert len(epub.spine) == 10
    toc = epub.toc()
    assert [entry.label for entry in toc] == NOVEL_CHAPTERS
    assert [entry.href for entry in toc] == epub.spine
    for entry in toc:
        assert text_of(epub.first_heading(entry.href)) == entry.label
    nested = {entry.label: [child.label for child in entry.children] for entry in toc}
    assert {k: v for k, v in nested.items() if v} == {k: [v] for k, v in NOVEL_NESTED.items()}
    for entry in toc:
        for child in entry.children:
            # A nested entry links to an anchor inside its parent chapter: the section title.
            path_, fragment = urldefrag(child.href)
            assert path_ == entry.href and fragment
            [target] = [e for e in epub.xml(path_).iter() if e.get("id") == fragment]
            assert target.tag in HEADINGS and text_of(target) == child.label


@pytest.mark.ac("RFL-AC16")
@pytest.mark.parametrize("source", [NO_OUTLINE, TWO_ENTRY_OUTLINE], ids=["none", "two-entries"])
def test_without_a_usable_outline_chapters_come_from_chapter_headings(
    source: Path, tmp_path: Path
) -> None:
    _, path = convert(source, tmp_path)
    epub = open_epub(path)

    toc = epub.toc()
    assert [entry.label for entry in toc] == NUMBERED_CHAPTERS
    # Each heading starts a chapter: its entry is the start of a file of its own, and
    # that file opens with the heading.
    assert [entry.href for entry in toc] == epub.spine
    for entry in toc:
        assert text_of(epub.first_heading(entry.href)) == entry.label


def emphasis(truth: list[str], mark: str) -> set[str]:
    """The words the ground truth marks ``*italic*`` (mark ``*``) or ``**bold**``."""
    pattern = r"\*\*([^*]+)\*\*" if mark == "**" else r"(?<!\*)\*([^*]+)\*(?!\*)"
    return {m for entry in truth for m in re.findall(pattern, entry)}


@pytest.mark.ac("RFL-AC13")
def test_headings_get_levels_from_size_and_weight_and_emphasis_is_kept(tmp_path: Path) -> None:
    _, path = convert(HEADINGS_SAMPLE, tmp_path)
    blocks = content_blocks(open_epub(path))

    levels = {b.text: b.tag.removeprefix(XHTML) for b in blocks if b.tag != f"{XHTML}p"}
    # The sample's 24 pt chapter titles and 14 pt bold section titles.
    assert levels == {
        "The First Chapter": "h1",
        "The Second Chapter": "h1",
        "The Ledger": "h2",
        "The Winter Entry": "h2",
        "What They Found": "h2",
    }
    truth = ground_truth(HEADINGS_SAMPLE)
    italic, bold = emphasis(truth, "*"), emphasis(truth, "**")
    assert italic == {"great", "underlined twice", "Mariner"}  # the ground truth is read right
    epub = open_epub(path)
    marked: dict[str, set[str]] = {"i": set(), "b": set()}
    for name in epub.spine:
        for p in epub.xml(name).iter(f"{XHTML}p"):
            for tag, found in marked.items():
                found.update(text_of(e) for e in p.iter(f"{XHTML}{tag}"))
    assert marked == {"i": italic, "b": bold}


@pytest.mark.ac("EPUB-AC5")
def test_chapter_markup_is_semantic(tmp_path: Path) -> None:
    _, path = convert(HEADINGS_SAMPLE, tmp_path)
    epub = open_epub(path)
    [caption] = [
        e[len("[Figure: ") : -1] for e in ground_truth(HEADINGS_SAMPLE) if e.startswith("[Figure:")
    ]

    tags: set[str] = set()
    figures: list[etree._Element] = []
    breaks: list[str] = []
    for name in epub.spine:
        root = epub.xml(name)
        assert root.get("lang") == "en"
        assert root.get("{http://www.w3.org/XML/1998/namespace}lang") == "en"
        tags.update(etree.QName(e).localname for e in root.iter() if isinstance(e.tag, str))
        figures.extend(root.iter(f"{XHTML}figure"))
        breaks.extend(
            str(e.get("aria-label")) for e in root.iter() if e.get(EPUB_TYPE) == "pagebreak"
        )
    assert {"h1", "h2", "b", "i"} <= tags
    assert len(figures) == 2
    captioned, plain = figures
    img = captioned.find(f"{XHTML}img")
    figcaption = captioned.find(f"{XHTML}figcaption")
    assert img is not None and figcaption is not None
    assert text_of(figcaption) == caption
    assert img.get("alt") == caption
    plain_img = plain.find(f"{XHTML}img")
    assert plain_img is not None and plain_img.get("alt") == "Figure 2"
    assert plain.find(f"{XHTML}figcaption") is None
    for figure in figures:
        image = figure.find(f"{XHTML}img")
        assert image is not None and epub.resolves(str(image.get("src")))
    # The sample's page labels are H-1 and H-2.
    assert breaks == ["H-1", "H-2"]


@pytest.mark.ac("EPUB-AC4")
def test_nav_and_ncx_carry_the_toc_page_list_and_landmarks(tmp_path: Path) -> None:
    _, path = convert(NOVEL, tmp_path)
    epub = open_epub(path)

    toc = epub.toc()
    assert len(toc) == 10
    assert all(epub.resolves(entry.href) for entry in toc)
    assert all(epub.resolves(c.href) for entry in toc for c in entry.children)
    pages = epub.nav("page-list").findall(f"{XHTML}ol/{XHTML}li/{XHTML}a")
    assert [a.text for a in pages] == [str(n) for n in range(1, 41)]
    assert all(epub.resolves(str(a.get("href"))) for a in pages)
    landmarks = epub.nav("landmarks").findall(f"{XHTML}ol/{XHTML}li/{XHTML}a")
    types = {str(a.get(EPUB_TYPE)): str(a.get("href")) for a in landmarks}
    assert {"toc", "bodymatter"} <= set(types)
    assert types["bodymatter"] == epub.spine[0]
    assert all(epub.resolves(href) for href in types.values())

    ncx = epub.xml("toc.ncx")
    nav_map = ncx.find(f"{NCX}navMap")
    assert nav_map is not None
    points = nav_map.findall(f"{NCX}navPoint")
    assert [text_of(p.find(f"{NCX}navLabel")) for p in points] == NOVEL_CHAPTERS  # type: ignore[arg-type]
    targets = ncx.findall(f"{NCX}pageList/{NCX}pageTarget")
    assert len(targets) == 40
    for target in targets:
        content = target.find(f"{NCX}content")
        assert content is not None and epub.resolves(str(content.get("src")))


@pytest.mark.ac("EPUB-AC6")
def test_an_oversized_chapter_is_split_at_paragraph_boundaries(tmp_path: Path) -> None:
    _, path = convert(OVERSIZED, tmp_path)
    epub = open_epub(path)
    truth = ground_truth(OVERSIZED)
    assert sum(len(p.encode()) for p in truth) > 900_000  # the fixture is what it claims

    assert len(epub.spine) >= 3
    whole = set(truth)
    paragraphs: list[str] = []
    for name in epub.spine:
        assert len(epub.archive.read(f"OEBPS/{name}")) <= 300 * 1024
        body = epub.xml(name).find(f"{XHTML}body")
        assert body is not None
        found = [text_of(p) for p in body.iter(f"{XHTML}p")]
        # Every part holds whole paragraphs only, so each starts at a paragraph boundary.
        assert found and all(p in whole for p in found)
        paragraphs.extend(found)
    assert paragraphs == truth
    toc = epub.toc()
    assert len(toc) == 1
    assert toc[0].href == epub.spine[0]


@pytest.mark.ac("MAIN-AC-A")
def test_novel_converts_cleanly_with_its_chapter_toc(
    tmp_path: Path, epubcheck: Callable[[Path], None]
) -> None:
    _, path = convert(NOVEL, tmp_path)
    epubcheck(path)  # zero epubcheck errors

    epub = open_epub(path)
    assert [entry.label for entry in epub.toc()] == NOVEL_CHAPTERS
    blocks = content_blocks(epub)
    truth = ground_truth(NOVEL)
    titles = set(NOVEL_CHAPTERS) | set(NOVEL_NESTED.values())
    # No running header and no page number in the text.
    assert not [b.text for b in blocks if "The Lantern Coast" in b.text]
    assert not [b.text for b in blocks if re.search(r"(^\d+\s|\s\d+$|^\W*\d+\W*$)", b.text)]
    # Every paragraph is whole: none is broken at a page boundary.
    assert [b.text for b in blocks if b.tag == f"{XHTML}p"] == [e for e in truth if e not in titles]
    assert [b.text for b in blocks if b.tag != f"{XHTML}p"] == [
        entry for entry in truth if entry in titles
    ]


GIANT = BORN_DIGITAL / "giant-paragraph.pdf"
IMAGE_ONLY = BORN_DIGITAL / "image-only.pdf"
IMAGE_BETWEEN_LINES = BORN_DIGITAL / "image-between-lines.pdf"
OUTLINE_TO_PAGE = BORN_DIGITAL / "outline-to-page.pdf"


@pytest.mark.ac("EPUB-AC15")
def test_a_paragraph_too_large_for_one_file_is_cut_at_word_boundaries(tmp_path: Path) -> None:
    _, path = convert(GIANT, tmp_path)
    epub = open_epub(path)
    [paragraph] = ground_truth(GIANT)
    assert len(paragraph.encode()) > 300 * 1024  # the fixture is what it claims

    assert len(epub.spine) >= 2
    parts: list[etree._Element] = []
    for name in epub.spine:
        assert len(epub.archive.read(f"OEBPS/{name}")) <= 300 * 1024
        parts.extend(epub.xml(name).iter(f"{XHTML}p"))
    assert " ".join(text_of(p) for p in parts) == paragraph
    assert parts[0].get("class") is None
    assert [p.get("class") for p in parts[1:]] == ["continued"] * (len(parts) - 1)


def test_a_page_with_only_an_image_is_content(tmp_path: Path) -> None:
    # RFL-R35: a kept book image is content, so this is no empty_document.
    _, path = convert(IMAGE_ONLY, tmp_path)
    epub = open_epub(path)

    images = [img for name in epub.spine for img in epub.xml(name).iter(f"{XHTML}img")]
    assert [img.get("alt") for img in images] == ["Figure 1"]
    assert epub.resolves(str(images[0].get("src")))


def test_an_image_between_two_lines_keeps_its_place(tmp_path: Path) -> None:
    _, path = convert(IMAGE_BETWEEN_LINES, tmp_path)
    epub = open_epub(path)
    before, after = ground_truth(IMAGE_BETWEEN_LINES)

    [name] = epub.spine
    body = epub.xml(name).find(f"{XHTML}body")
    assert body is not None
    order = [
        (etree.QName(e).localname, text_of(e)) for e in body if e.get(EPUB_TYPE) != "pagebreak"
    ]
    assert order == [("p", before), ("figure", ""), ("p", after)]


def test_a_nested_outline_entry_without_a_heading_links_to_its_page(tmp_path: Path) -> None:
    _, path = convert(OUTLINE_TO_PAGE, tmp_path)
    epub = open_epub(path)

    toc = epub.toc()
    assert [entry.label for entry in toc] == ["One", "Two", "Four"]
    [three] = toc[1].children
    assert three.label == "Three"
    file, fragment = urldefrag(three.href)
    assert file == toc[1].href and fragment == "page-3"
    assert epub.resolves(three.href)


IMAGE_PAGE = BORN_DIGITAL / "image-page-in-paragraph.pdf"


def test_a_paragraph_runs_on_past_a_page_of_images_only(tmp_path: Path) -> None:
    # RFL-R18: the join skips over images; the image comes after the joined paragraph.
    _, path = convert(IMAGE_PAGE, tmp_path)
    epub = open_epub(path)
    [paragraph] = ground_truth(IMAGE_PAGE)

    [name] = epub.spine
    body = epub.xml(name).find(f"{XHTML}body")
    assert body is not None
    kinds = [etree.QName(e).localname for e in body if e.get(EPUB_TYPE) != "pagebreak"]
    assert kinds == ["p", "figure"]
    p = body.find(f"{XHTML}p")
    assert p is not None and text_of(p) == paragraph
    inline = [str(e.get("id")) for e in p.iter() if e.get(EPUB_TYPE) == "pagebreak"]
    assert inline == ["page-2", "page-3"]
