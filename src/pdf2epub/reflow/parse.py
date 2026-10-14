"""Parsing a source PDF's pages with pdfminer.six, treating the file as untrusted
(RFL-R2, RFL-R3, RFL-R5, RFL-R6).

pdfminer only lays pages out: it never runs JavaScript or actions, never follows links
and never fetches anything an external stream names. What it would decode is checked
first: every content stream (pages and form XObjects alike) against the decompressed
stream size limit before pdfminer inflates it, and every image against the pixel limit
by the dimensions it declares (images are never decoded here).
"""

from collections.abc import Iterator, Sequence
from contextlib import AbstractContextManager
from pathlib import Path
from types import TracebackType
from typing import BinaryIO

from pdfminer.converter import PDFPageAggregator
from pdfminer.layout import LAParams, LTContainer, LTImage, LTItem, LTPage
from pdfminer.pdfdocument import PDFDocument, PDFXRefFallback
from pdfminer.pdfinterp import PDFPageInterpreter, PDFResourceManager
from pdfminer.pdfpage import PDFPage
from pdfminer.pdfparser import PDFParser
from pdfminer.pdftypes import LITERALS_FLATE_DECODE, PDFStream, resolve1
from pdfminer.psexceptions import PSException

from pdf2epub.reflow.limits import ResourceLimitExceeded, check_image, check_inflated_size
from pdf2epub.reflow.source import CorruptPdf


class ParsedPdf(AbstractContextManager["ParsedPdf"]):
    """An open PDF, ready to be laid out page by page."""

    def __init__(self, path: Path) -> None:
        self._file: BinaryIO = path.open("rb")
        try:
            self._document = PDFDocument(PDFParser(self._file))
        except PSException as error:
            self._file.close()
            raise CorruptPdf(f"The PDF can't be parsed, even with repair: {error}") from error
        except BaseException:
            self._file.close()
            raise

    @property
    def repaired(self) -> bool:
        """True when the cross-reference table had to be rebuilt by scanning the file."""
        return any(isinstance(xref, PDFXRefFallback) for xref in self._document.xrefs)

    def pages(self) -> Iterator[PDFPage]:
        try:
            yield from PDFPage.create_pages(self._document)
        except PSException as error:
            raise CorruptPdf(f"The PDF's page tree can't be read: {error}") from error

    def layouts(self, laparams: LAParams) -> Iterator[LTPage]:
        """Each page's layout, in order. Raises ``ResourceLimitExceeded`` naming the page
        where a limit is hit, and ``CorruptPdf`` if a page can't be parsed."""
        manager = PDFResourceManager(caching=True)
        device = PDFPageAggregator(manager, laparams=laparams)
        interpreter = _GuardedInterpreter(manager, device)
        for number, page in enumerate(self.pages(), start=1):
            try:
                interpreter.process_page(page)
                layout = device.get_result()
                _check_images(layout)
            except ResourceLimitExceeded as error:
                raise error.on_page(number) from None
            except PSException as error:
                raise CorruptPdf(f"Page {number} can't be parsed: {error}") from error
            yield layout

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self._file.close()


class _GuardedInterpreter(PDFPageInterpreter):
    """Checks each content stream's inflated size before pdfminer decodes it. Form
    XObjects run in a copy made by ``dup()``, which is this class too."""

    def execute(self, streams: Sequence[object]) -> None:
        for obj in streams:
            stream = resolve1(obj)
            if isinstance(stream, PDFStream):
                _check_stream(stream)
        super().execute(streams)


def _check_stream(stream: PDFStream) -> None:
    if stream.rawdata is None:  # already decoded (and checked) once
        return
    filters = [name for name, _ in stream.get_filters()]
    flate = 0
    while flate < len(filters) and filters[flate] in LITERALS_FLATE_DECODE:
        flate += 1
    if flate:
        check_inflated_size(stream.rawdata, flate)


def _check_images(item: LTItem) -> None:
    if isinstance(item, LTImage):
        width, height = (_dimension(value) for value in item.srcsize)
        check_image(width, height)
    elif isinstance(item, LTContainer):
        for child in item:
            _check_images(child)


def _dimension(value: object) -> int:
    value = resolve1(value)
    if isinstance(value, int | float) and not isinstance(value, bool) and value > 0:
        return int(value)
    return 0
