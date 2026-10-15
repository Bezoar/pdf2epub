"""Opening a source PDF: what the rest of the conversion needs from the file as a whole
(RFL-R1: pypdfium2 for page labels, the outline and metadata, pdfminer.six for layout)."""

import ctypes
import hashlib
import io
from collections.abc import Collection
from dataclasses import dataclass, field
from pathlib import Path

import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_c
from pdfminer.pdfdocument import PDFDocument
from pdfminer.pdfpage import PDFPage
from pdfminer.pdfparser import PDFParser
from pdfminer.psexceptions import PSException

from pdf2epub.passwords import Secret


class CorruptPdf(Exception):
    """The PDF can't be parsed at all, even with repair (RFL-R2)."""


@dataclass(frozen=True)
class OutlineEntry:
    """One entry of the PDF outline (bookmarks), in outline order."""

    level: int
    """0 for a top-level entry, 1 for an entry nested in it, and so on."""
    title: str
    page: int | None
    """The 1-based page it points to, or None when it doesn't resolve to a page."""
    top: float | None
    """Where on that page it points, measured from the top; None for the whole page."""


@dataclass(frozen=True)
class SourcePdf:
    """A source PDF, opened once and described without any PDF objects."""

    path: Path
    sha256: str
    page_labels: list[str]
    """The printed label of each page, by index; a page with no label gets its 1-based
    index (RFL-R25)."""
    info: dict[str, str]
    """The Info dictionary's non-empty entries, e.g. ``Title``, ``Author``, ``ModDate``."""
    language: str | None
    """The catalog ``/Lang``, if any."""
    outline: list[OutlineEntry] = field(default_factory=list)
    xmp: bytes | None = None
    """The XMP metadata packet, if any, as read by ``ParsedPdf.xmp``."""
    unloadable: frozenset[int] = frozenset()
    """The 1-based pages pdfium counts but can't load (RFL-R37)."""

    @property
    def page_count(self) -> int:
        return len(self.page_labels)


def open_source(path: Path, password: Secret | None = None) -> SourcePdf:
    """Open ``path`` with pdfium, which repairs what it can, with ``password`` if it
    needs one. Raises ``CorruptPdf`` when even that fails, or when pdfium can load none of
    the pages it counts (RFL-R37). A PDF with no pages comes back with ``page_count`` 0."""
    data = path.read_bytes()
    try:
        document = pdfium.PdfDocument(
            data, password=password.reveal() if password is not None else None
        )
    except pdfium.PdfiumError as error:
        if _has_no_pages(data):
            # pdfium declines a document whose page tree is empty without setting an
            # error code of its own, so err_code is whatever the last failure left.
            return SourcePdf(path, hashlib.sha256(data).hexdigest(), [], {}, None)
        if error.err_code in _CORRUPT:
            raise CorruptPdf(f"The PDF can't be parsed, even with repair: {error}") from error
        raise
    try:
        unloadable = _unloadable_pages(document)
        if unloadable and len(unloadable) == len(document):
            raise CorruptPdf("No page of the PDF can be read, even with repair")
        labels = [document.get_page_label(i) or str(i + 1) for i in range(len(document))]
        info = {key: value for key, value in document.get_metadata_dict(skip_empty=True).items()}
        language = _catalog_language(document)
        outline = _outline(document, unloadable)
    finally:
        document.close()
    return SourcePdf(
        path=path,
        sha256=hashlib.sha256(data).hexdigest(),
        page_labels=labels,
        info=info,
        language=language,
        outline=outline,
        unloadable=unloadable,
    )


def page_text(path: Path, pages: Collection[int], password: Secret | None = None) -> dict[int, str]:
    """The text pdfium reads on each of ``pages`` (1-based) of ``path``, opened with
    ``password`` if it needs one: a page's text where pdfminer.six has no page to read it
    from (RFL-R37)."""
    if not pages:
        return {}
    document = pdfium.PdfDocument(path, password=password.reveal() if password else None)
    try:
        texts: dict[int, str] = {}
        for number in sorted(pages):
            page = document[number - 1]
            try:
                textpage = page.get_textpage()
                try:
                    texts[number] = textpage.get_text_range()
                finally:
                    textpage.close()
            finally:
                page.close()
        return texts
    finally:
        document.close()


# The most outline entries read, and the deepest nesting followed: an outline is a tree
# the file describes, so it is bounded like anything else in it.
_MAX_OUTLINE, _MAX_OUTLINE_DEPTH = 10_000, 15
# Where each view mode that has a top keeps it among its parameters (PDF 32000-1
# 12.3.2.2, pdfium's PDFDEST_VIEW_* codes): XYZ [left top zoom], FitH [top],
# FitR [left bottom right top], FitBH [top]. The other modes show the whole page.
_TOP_PARAMETER = {
    pdfium_c.PDFDEST_VIEW_XYZ: 1,
    pdfium_c.PDFDEST_VIEW_FITH: 0,
    pdfium_c.PDFDEST_VIEW_FITR: 3,
    pdfium_c.PDFDEST_VIEW_FITBH: 0,
}


def _outline(document: pdfium.PdfDocument, unloadable: Collection[int]) -> list[OutlineEntry]:
    entries: list[OutlineEntry] = []
    for item in document.get_toc(max_depth=_MAX_OUTLINE_DEPTH):
        if len(entries) == _MAX_OUTLINE:
            break
        page = top = None
        destination = item.get_dest()
        index = destination.get_index() if destination is not None else None
        if index is not None and 0 <= index < len(document):
            page = index + 1
            mode, params = destination.get_view() if destination is not None else (0, [])
            at = _TOP_PARAMETER.get(mode)
            # pdfium reports a null (unchanged) top as 0, which no real view uses. A page
            # pdfium can't load has no size to measure the top from.
            if at is not None and len(params) > at and params[at] and page not in unloadable:
                top = max(document.get_page_size(index)[1] - float(params[at]), 0.0)
        title = " ".join(item.get_title().split())
        entries.append(OutlineEntry(item.level, title, page, top))
    return entries


# pdfium's load errors that mean the file itself is broken: all but the password and
# security-handler failures, which are about access, not damage.
_CORRUPT = (
    pdfium_c.FPDF_ERR_SUCCESS,
    pdfium_c.FPDF_ERR_UNKNOWN,
    pdfium_c.FPDF_ERR_FILE,
    pdfium_c.FPDF_ERR_FORMAT,
    pdfium_c.FPDF_ERR_PAGE,
)


def _unloadable_pages(document: pdfium.PdfDocument) -> frozenset[int]:
    """The 1-based pages in the page count that pdfium can't find: no later stage may ask
    pdfium to render or read them."""
    unloadable: set[int] = set()
    for index in range(len(document)):
        try:
            document.get_page_size(index)  # finds the page as loading it does
        except pdfium.PdfiumError:
            unloadable.add(index + 1)
    return frozenset(unloadable)


def _has_no_pages(data: bytes) -> bool:
    """True when pdfminer reads the document and finds an empty page tree."""
    try:
        document = PDFDocument(PDFParser(io.BytesIO(data)))
        return next(PDFPage.create_pages(document), None) is None
    except (PSException, RecursionError):  # a loop in a damaged file: not empty, broken
        return False


def _catalog_language(document: pdfium.PdfDocument) -> str | None:
    """The catalog's ``/Lang`` entry, through pdfium's UTF-16LE buffer protocol."""
    size = pdfium_c.FPDFCatalog_GetLanguage(document, None, 0)
    if size <= 2:  # empty: just the terminator, or no entry at all
        return None
    buffer = ctypes.create_string_buffer(size)
    pdfium_c.FPDFCatalog_GetLanguage(
        document, ctypes.cast(buffer, ctypes.POINTER(pdfium_c.FPDF_WCHAR)), size
    )
    language = buffer.raw[: size - 2].decode("utf-16-le").strip()
    return language or None
