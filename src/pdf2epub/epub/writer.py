"""pdf2epub's EPUB 3 writer (EPUB-R1): the standard library's ``zipfile``, Jinja2 templates
and lxml for the built-in checks. It renders only from the document model.

Package layout (EPUB-R2, EPUB-R4)::

    mimetype                      stored, first
    META-INF/container.xml        points to OEBPS/content.opf
    OEBPS/content.opf             package document
    OEBPS/nav.xhtml               navigation document (first in the spine, non-linear)
    OEBPS/toc.ncx                 EPUB 2 table of contents (EPUB-R6)
    OEBPS/style.css               default stylesheet (EPUB-R10)
    OEBPS/chapter-NNN.xhtml       one file per chapter, in document order

Output is deterministic (EPUB-R15): entries in sorted order after ``mimetype``, fixed
timestamps, a fixed compression level, and names and ids derived from document order.
"""

import io
import posixpath
import zipfile
from dataclasses import dataclass, field
from importlib.resources import files
from typing import Any
from urllib.parse import urldefrag

from jinja2 import Environment, FunctionLoader, StrictUndefined
from lxml import etree

from pdf2epub.reflow.model import (
    Block,
    Document,
    Heading,
    Inline,
    LineBlock,
    PageBreak,
    Paragraph,
    Text,
    TocEntry,
)

MIMETYPE = b"application/epub+zip"
CONTAINER = "META-INF/container.xml"
PACKAGE_DIR = "OEBPS"
PACKAGE = f"{PACKAGE_DIR}/content.opf"
NAV, NCX, STYLESHEET = "nav.xhtml", "toc.ncx", "style.css"
ZIP_TIME = (1980, 1, 1, 0, 0, 0)
COMPRESS_LEVEL = 9

XHTML = "application/xhtml+xml"
MEDIA_TYPES = {".xhtml": XHTML, ".css": "text/css", ".ncx": "application/x-dtbncx+xml"}


class PackageCheckError(Exception):
    """A built-in check failed (EPUB-R16). This is a bug in pdf2epub, never in the input."""


def _template_source(name: str) -> str:
    return files("pdf2epub.epub").joinpath("templates", name).read_text(encoding="utf-8")


_ENV = Environment(
    loader=FunctionLoader(_template_source),
    autoescape=True,
    undefined=StrictUndefined,
    keep_trailing_newline=True,
)


def chapter_file(index: int) -> str:
    return f"chapter-{index + 1:03d}.xhtml"


def page_id(page: int) -> str:
    """The ID of a page's break marker: from the PDF page index only (EPUB-R19)."""
    return f"page-{page}"


@dataclass
class _Nav:
    id: str
    label: str
    href: str
    children: list["_Nav"] = field(default_factory=list)


def write_epub(document: Document) -> bytes:
    """The EPUB for ``document``, as bytes. Raises ``PackageCheckError`` if the package
    fails a built-in check."""
    meta = document.metadata
    contents: dict[str, bytes] = {}

    page_list: list[_Nav] = []
    for index, chapter in enumerate(document.chapters):
        name = chapter_file(index)
        page_list.extend(
            _Nav(f"pt-{b.page}", b.label, f"{name}#{page_id(b.page)}")
            for b in _page_breaks(chapter.blocks)
        )
        contents[name] = _render(
            "chapter.xhtml.j2",
            meta=meta,
            title=chapter.title or meta.title,
            stylesheet=STYLESHEET,
            blocks=[_block(block) for block in chapter.blocks],
        )

    counter = iter(range(1, 1_000_000))
    toc = [_toc_entry(entry, counter) for entry in document.toc]
    landmarks = [
        {"type": "toc", "href": f"{NAV}#toc", "label": "Contents"},
        {"type": "bodymatter", "href": chapter_file(0), "label": "Start of content"},
    ]
    contents[NAV] = _render(
        "nav.xhtml.j2",
        meta=meta,
        stylesheet=STYLESHEET,
        toc=toc,
        page_list=page_list,
        landmarks=landmarks,
    )
    contents[NCX] = _render(
        "toc.ncx.j2", meta=meta, toc=toc, page_list=page_list, depth=_depth(toc)
    )
    contents[STYLESHEET] = _template_source(STYLESHEET).encode("utf-8")

    chapters = [chapter_file(i) for i in range(len(document.chapters))]
    manifest = [
        {"id": "nav", "href": NAV, "media_type": XHTML, "properties": "nav"},
        {"id": "ncx", "href": NCX, "media_type": MEDIA_TYPES[".ncx"], "properties": None},
        {"id": "style", "href": STYLESHEET, "media_type": "text/css", "properties": None},
    ] + [
        {"id": name.removesuffix(".xhtml"), "href": name, "media_type": XHTML, "properties": None}
        for name in chapters
    ]
    spine = [{"idref": "nav", "linear": False}] + [
        {"idref": name.removesuffix(".xhtml"), "linear": True} for name in chapters
    ]
    package = _render("content.opf.j2", meta=meta, manifest=manifest, spine=spine, ncx_id="ncx")

    entries = {f"{PACKAGE_DIR}/{name}": data for name, data in contents.items()}
    entries[PACKAGE] = package
    entries[CONTAINER] = _render("container.xml.j2", package_path=PACKAGE)
    check_package(entries)
    return _zip(entries)


def _render(template: str, **context: Any) -> bytes:
    return _ENV.get_template(template).render(**context).encode("utf-8")


def _page_breaks(blocks: list[Block]) -> list[PageBreak]:
    breaks: list[PageBreak] = []
    for block in blocks:
        if isinstance(block, PageBreak):
            breaks.append(block)
        elif isinstance(block, Heading | Paragraph):
            breaks.extend(i for i in block.inlines if isinstance(i, PageBreak))
        elif isinstance(block, LineBlock):
            breaks.extend(i for line in block.lines for i in line if isinstance(i, PageBreak))
    return breaks


def _inline(inline: Inline) -> dict[str, Any]:
    if isinstance(inline, PageBreak):
        return {"kind": "pagebreak", "id": page_id(inline.page), "label": inline.label}
    assert isinstance(inline, Text)
    return {"kind": "text", "text": inline.text, "bold": inline.bold, "italic": inline.italic}


def _block(block: Block) -> dict[str, Any]:
    if isinstance(block, PageBreak):
        return _inline(block)
    if isinstance(block, Heading):
        return {
            "kind": "heading",
            "level": min(max(block.level, 1), 6),
            "id": block.anchor,
            "inlines": [_inline(i) for i in block.inlines],
        }
    if isinstance(block, LineBlock):
        # EPUB-R20: one <p class="lines">, a <br/> between lines; code also in <code>.
        return {
            "kind": "lines",
            "monospace": block.monospace,
            "lines": [[_inline(i) for i in line] for line in block.lines],
        }
    return {"kind": "paragraph", "inlines": [_inline(i) for i in block.inlines]}


def _toc_entry(entry: TocEntry, counter: Any) -> _Nav:
    href = chapter_file(entry.chapter) + (f"#{entry.anchor}" if entry.anchor else "")
    nav = _Nav(f"nav-{next(counter)}", entry.label, href)
    nav.children = [_toc_entry(child, counter) for child in entry.children]
    return nav


def _depth(entries: list[_Nav]) -> int:
    return 1 + max((_depth(e.children) for e in entries if e.children), default=0)


def _zip(entries: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        stored = zipfile.ZipInfo("mimetype", date_time=ZIP_TIME)
        stored.compress_type = zipfile.ZIP_STORED
        archive.writestr(stored, MIMETYPE)
        for name in sorted(entries):
            info = zipfile.ZipInfo(name, date_time=ZIP_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, entries[name], compresslevel=COMPRESS_LEVEL)
    return buffer.getvalue()


def check_package(entries: dict[str, bytes]) -> None:
    """The built-in checks run before anything is written (EPUB-R16): XML files are
    well-formed, the manifest and the package agree, every internal link resolves, and
    the spine is not empty."""
    trees: dict[str, etree._Element] = {}
    for name, data in entries.items():
        if name.endswith((".xhtml", ".opf", ".ncx", ".xml")):
            try:
                trees[name] = etree.fromstring(data)
            except etree.XMLSyntaxError as error:
                raise PackageCheckError(f"{name} is not well-formed: {error}") from error

    opf = trees[PACKAGE]
    ns = {"opf": "http://www.idpf.org/2007/opf"}
    hrefs = {
        posixpath.join(PACKAGE_DIR, str(item.get("href"))): item
        for item in opf.iterfind("opf:manifest/opf:item", ns)
    }
    packaged = set(entries) - {CONTAINER, PACKAGE}
    if set(hrefs) != packaged:
        raise PackageCheckError(f"manifest and package differ: {sorted(set(hrefs) ^ packaged)}")
    if not opf.findall("opf:spine/opf:itemref", ns):
        raise PackageCheckError("the spine is empty")

    ids = {
        name: {str(element.get("id")) for element in tree.iter() if element.get("id")}
        for name, tree in trees.items()
    }
    for name, tree in trees.items():
        if not name.endswith((".xhtml", ".ncx")):
            continue
        for element in tree.iter():
            tag = etree.QName(element).localname if isinstance(element.tag, str) else ""
            link = element.get("href") if tag == "a" else element.get("src")
            if tag not in ("a", "content") or link is None:
                continue
            path, fragment = urldefrag(link)
            target = posixpath.normpath(posixpath.join(posixpath.dirname(name), path))
            if target not in entries or (fragment and fragment not in ids.get(target, set())):
                raise PackageCheckError(f"{name} links to missing {link}")
