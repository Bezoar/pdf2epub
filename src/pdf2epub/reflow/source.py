"""Opening a source PDF: what the rest of the conversion needs from the file as a whole
(RFL-R1: pypdfium2 for page labels and metadata, pdfminer.six for layout)."""

import ctypes
import hashlib
from dataclasses import dataclass
from pathlib import Path

import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_c


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


def open_source(path: Path) -> SourcePdf:
    data = path.read_bytes()
    document = pdfium.PdfDocument(data)
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
