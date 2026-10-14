"""pdf2epub's EPUB 3 writer (EPUB-R1): the standard library's ``zipfile``, Jinja2 templates
and lxml for the built-in checks. It renders only from the document model.

Package layout (EPUB-R2, EPUB-R4)::

    mimetype                      stored, first
    META-INF/container.xml        points to OEBPS/content.opf
    OEBPS/content.opf             package document
    OEBPS/nav.xhtml               navigation document (first in the spine, non-linear)
    OEBPS/toc.ncx                 EPUB 2 table of contents (EPUB-R6)
    OEBPS/style.css               default stylesheet (EPUB-R10)
    OEBPS/cover.xhtml             the cover page, first in the spine (EPUB-R12)
    OEBPS/images/cover.jpg|png    the cover image (manifest property cover-image)
    OEBPS/chapter-NNN.xhtml       each chapter, in document order; a chapter split for
    OEBPS/chapter-NNN-P.xhtml     size (EPUB-R8) goes on in parts 2, 3, ...
    OEBPS/images/image-NNN.jpg/png  book images, each stored once

Output is deterministic (EPUB-R15): entries in sorted order after ``mimetype``, fixed
timestamps, a fixed compression level, and names and ids derived from document order.
"""

import io
import posixpath
import re
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass, field
from html import escape
from importlib.resources import files
from typing import Any
from urllib.parse import urldefrag

from jinja2 import Environment, FunctionLoader, StrictUndefined
from lxml import etree

from pdf2epub.reflow.model import (
    Block,
    Document,
    Heading,
    Image,
    ImageAsset,
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
NAV, NCX, STYLESHEET, COVER = "nav.xhtml", "toc.ncx", "style.css", "cover.xhtml"
ZIP_TIME = (1980, 1, 1, 0, 0, 0)
COMPRESS_LEVEL = 9

XHTML = "application/xhtml+xml"
MEDIA_TYPES = {".xhtml": XHTML, ".css": "text/css", ".ncx": "application/x-dtbncx+xml"}
IMAGE_EXTENSIONS = {"image/png": ".png", "image/jpeg": ".jpg", "image/gif": ".gif"}
SPLIT_BYTES = 300_000
"""A chapter file is split at block boundaries to stay at or below this size (EPUB-R8)."""


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


def chapter_file(index: int, part: int = 0) -> str:
    """The file of a chapter's ``part`` (0 for the first, or only, part)."""
    suffix = f"-{part + 1}" if part else ""
    return f"chapter-{index + 1:03d}{suffix}.xhtml"


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
    images = {
        asset: f"images/image-{n:03d}{IMAGE_EXTENSIONS[asset.media_type]}"
        for n, asset in enumerate(dict.fromkeys(document.images), start=1)
    }
    figures = iter(range(1, 1_000_000))

    page_list: list[_Nav] = []
    chapter_files: list[list[str]] = []
    where: dict[str, str] = {}
    """The file each block ID is in."""
    for index, chapter in enumerate(document.chapters):
        title = chapter.title or meta.title
        shell = len(_chapter(meta, title, ""))
        parts: list[list[tuple[Block, str]]] = [[]]
        size = shell
        for block in chapter.blocks:
            markup = _block_markup(_block(block, images, figures))
            oversized = len(markup.encode("utf-8")) + shell > SPLIT_BYTES
            rendered_pieces: list[tuple[Block, str]] = [(block, markup)]
            if oversized and isinstance(block, Paragraph):
                rendered_pieces = [
                    (piece, _block_markup(_block(piece, images, figures, continued=n > 0)))
                    for n, piece in enumerate(_paragraph_pieces(block, SPLIT_BYTES - shell))
                ]
            elif oversized and isinstance(block, LineBlock):
                rendered_pieces = _line_block_pieces(block, SPLIT_BYTES - shell)
            # No file may pass the limit: a block that can't be cut small enough is a bug
            # report, not an oversized file (EPUB-R8, EPUB-R21).
            if any(len(m.encode("utf-8")) + shell > SPLIT_BYTES for _, m in rendered_pieces):
                raise PackageCheckError(f"a block in chapter {index + 1} is too large to split")
            for piece, piece_markup in rendered_pieces:
                rendered = len(piece_markup.encode("utf-8")) + 1
                if parts[-1] and size + rendered > SPLIT_BYTES:
                    parts.append([])
                    size = shell
                parts[-1].append((piece, piece_markup))
                size += rendered
        names: list[str] = []
        for part, items in enumerate(parts):
            name = chapter_file(index, part)
            names.append(name)
            for block, _ in items:
                for marker in _page_breaks([block]):
                    page_list.append(
                        _Nav(f"pt-{marker.page}", marker.label, f"{name}#{page_id(marker.page)}")
                    )
                    where[page_id(marker.page)] = name
                if isinstance(block, Heading):
                    where[block.anchor] = name
            body = "\n".join(markup for _, markup in items)
            contents[name] = _chapter(meta, title, body)
        chapter_files.append(names)

    counter = iter(range(1, 1_000_000))
    toc = [_toc_entry(entry, counter, chapter_files, where) for entry in document.toc]
    body_start = next((i for i, c in enumerate(document.chapters) if c.title is not None), 0)
    cover_image = None
    if document.cover is not None:
        # EPUB-R12: the cover image, and a cover page showing it, first in the spine.
        cover_image = f"images/cover{IMAGE_EXTENSIONS[document.cover.media_type]}"
        contents[cover_image] = document.cover.data
        markup = f'<div class="cover"><img src="{escape(cover_image)}" alt="Cover"/></div>'
        contents[COVER] = _chapter(meta, meta.title, markup)
    landmarks = [
        *([{"type": "cover", "href": COVER, "label": "Cover"}] if cover_image else []),
        {"type": "toc", "href": f"{NAV}#toc", "label": "Contents"},
        {"type": "bodymatter", "href": chapter_files[body_start][0], "label": "Start of content"},
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
    for asset, name in images.items():
        contents[name] = asset.data

    chapters = [name for names in chapter_files for name in names]
    manifest = (
        [
            {"id": "nav", "href": NAV, "media_type": XHTML, "properties": "nav"},
            {"id": "ncx", "href": NCX, "media_type": MEDIA_TYPES[".ncx"], "properties": None},
            {"id": "style", "href": STYLESHEET, "media_type": "text/css", "properties": None},
        ]
        + [
            {
                "id": name.removesuffix(".xhtml"),
                "href": name,
                "media_type": XHTML,
                "properties": None,
            }
            for name in chapters
        ]
        + [
            {
                "id": posixpath.basename(name).rsplit(".", 1)[0],
                "href": name,
                "media_type": asset.media_type,
                "properties": None,
            }
            for asset, name in images.items()
        ]
    )
    cover_spine = []
    if cover_image is not None:
        assert document.cover is not None
        manifest += [
            {"id": "cover", "href": COVER, "media_type": XHTML, "properties": None},
            {
                "id": "cover-image",
                "href": cover_image,
                "media_type": document.cover.media_type,
                "properties": "cover-image",
            },
        ]
        cover_spine = [{"idref": "cover", "linear": True}]
    spine = [*cover_spine, {"idref": "nav", "linear": False}] + [
        {"idref": name.removesuffix(".xhtml"), "linear": True} for name in chapters
    ]
    package = _render("content.opf.j2", meta=meta, manifest=manifest, spine=spine, ncx_id="ncx")

    entries = {f"{PACKAGE_DIR}/{name}": data for name, data in contents.items()}
    entries[PACKAGE] = package
    entries[CONTAINER] = _render("container.xml.j2", package_path=PACKAGE)
    check_package(entries)
    return _zip(entries)


def _block_markup(node: dict[str, Any]) -> str:
    """One block's XHTML, from the ``block`` macro."""
    macro = getattr(_ENV.get_template("blocks.xhtml.j2").module, "block")  # noqa: B009  # Jinja exposes macros as module attributes
    return str(macro(node))


def _chapter(meta: Any, title: str, body: str) -> bytes:
    return _render("chapter.xhtml.j2", meta=meta, title=title, stylesheet=STYLESHEET, body=body)


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


# What a paragraph's wrapper (``<p class="continued">`` ... ``</p>``, indented) and each
# word or page-break marker add to its markup, at most: a word's escaped text plus room for
# its ``<b><i>`` ... ``</i></b>`` tags, or the marker's span.
_WRAPPER_MARKUP, _INLINE_MARKUP, _MARKER_MARKUP = 64, 16, 160


def _paragraph_pieces(paragraph: Paragraph, budget: int) -> list[Paragraph]:
    """A paragraph too large for one chapter file, cut at word boundaries into pieces
    whose markup fits within ``budget`` bytes (EPUB-R21). A single word too long for
    a piece on its own is cut between characters."""
    pieces: list[list[Inline]] = [[]]
    size = _WRAPPER_MARKUP
    for inline in paragraph.inlines:
        tokens: list[tuple[Inline, int]]
        if isinstance(inline, PageBreak):
            tokens = [(inline, _MARKER_MARKUP)]
        else:
            tokens = [
                (Text(chunk, inline.bold, inline.italic), _cost(chunk))
                for word in re.findall(r"\S+\s*|\s+", inline.text)
                for chunk in _chunks(word, budget - _WRAPPER_MARKUP)
            ]
        for token, cost in tokens:
            if pieces[-1] and size + cost > budget:
                pieces.append([])
                size = _WRAPPER_MARKUP
            pieces[-1].append(token)
            size += cost
    return [Paragraph(inlines) for inlines in pieces]


def _line_block_pieces(block: LineBlock, budget: int) -> list[tuple[Block, str]]:
    """A line block too large for one chapter file, cut between its lines into line blocks
    whose markup each fits within ``budget`` bytes where a single line allows."""
    pieces: list[tuple[Block, str]] = []
    lines: list[list[Inline]] = []
    for line in block.lines:
        trial = LineBlock([*lines, line], block.monospace)
        markup = _block_markup(_block(trial, {}, iter(())))
        if lines and len(markup.encode("utf-8")) > budget:
            done = LineBlock(lines, block.monospace)
            pieces.append((done, _block_markup(_block(done, {}, iter(())))))
            lines = []
        lines.append(line)
    rest = LineBlock(lines, block.monospace)
    pieces.append((rest, _block_markup(_block(rest, {}, iter(())))))
    return pieces


def _cost(text: str) -> int:
    return len(escape(text).encode("utf-8")) + _INLINE_MARKUP


def _chunks(word: str, budget: int) -> list[str]:
    """``word`` as one chunk, or cut between characters into chunks that each cost at most
    ``budget``."""
    if _cost(word) <= budget:
        return [word]
    chunks = [""]
    for char in word:
        if chunks[-1] and _cost(chunks[-1] + char) > budget:
            chunks.append("")
        chunks[-1] += char
    return chunks


def _block(
    block: Block,
    images: dict[ImageAsset, str],
    figures: Iterator[int],
    continued: bool = False,
) -> dict[str, Any]:
    if isinstance(block, PageBreak):
        return _inline(block)
    if isinstance(block, Image):
        # EPUB-R11: the caption, or "Figure <n>" numbered within the book.
        number = next(figures)
        return {
            "kind": "figure",
            "src": images[block.asset],
            "alt": block.caption or f"Figure {number}",
            "caption": block.caption,
        }
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
    return {
        "kind": "paragraph",
        "continued": continued,
        "inlines": [_inline(i) for i in block.inlines],
    }


def _toc_entry(
    entry: TocEntry, counter: Iterator[int], files: list[list[str]], where: dict[str, str]
) -> _Nav:
    if entry.anchor is None:
        href = files[entry.chapter][0]
    else:
        # An anchor no file holds keeps its fragment, so the package check catches it.
        href = f"{where.get(entry.anchor, files[entry.chapter][0])}#{entry.anchor}"
    nav = _Nav(f"nav-{next(counter)}", entry.label, href)
    nav.children = [_toc_entry(child, counter, files, where) for child in entry.children]
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
            if tag not in ("a", "content", "img") or link is None:
                continue
            path, fragment = urldefrag(link)
            target = posixpath.normpath(posixpath.join(posixpath.dirname(name), path))
            if target not in entries or (fragment and fragment not in ids.get(target, set())):
                raise PackageCheckError(f"{name} links to missing {link}")
