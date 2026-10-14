"""Opening a source PDF: what the rest of the conversion needs from the file as a whole
(RFL-R1: pypdfium2 for page labels and metadata, pdfminer.six for layout)."""

import ctypes
import hashlib
import io
from dataclasses import dataclass
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

    @property
    def page_count(self) -> int:
        return len(self.page_labels)


def open_source(path: Path, password: Secret | None = None) -> SourcePdf:
    """Open ``path`` with pdfium, which repairs what it can, with ``password`` if it
    needs one. Raises ``CorruptPdf`` when even that fails. A PDF with no pages comes back
    with ``page_count`` 0."""
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
        labels = [document.get_page_label(i) or str(i + 1) for i in range(len(document))]
        info = {key: value for key, value in document.get_metadata_dict(skip_empty=True).items()}
        language = _catalog_language(document)
    finally:
        document.close()
    return SourcePdf(
        path=path,
        sha256=hashlib.sha256(data).hexdigest(),
        page_labels=labels,
        info=info,
        language=language,
    )


# pdfium's load errors that mean the file itself is broken: all but the password and
# security-handler failures, which are about access, not damage.
_CORRUPT = (
    pdfium_c.FPDF_ERR_SUCCESS,
    pdfium_c.FPDF_ERR_UNKNOWN,
    pdfium_c.FPDF_ERR_FILE,
    pdfium_c.FPDF_ERR_FORMAT,
    pdfium_c.FPDF_ERR_PAGE,
)


def _has_no_pages(data: bytes) -> bool:
    """True when pdfminer reads the document and finds an empty page tree."""
    try:
        document = PDFDocument(PDFParser(io.BytesIO(data)))
        return next(PDFPage.create_pages(document), None) is None
    except PSException:
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
