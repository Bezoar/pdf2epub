"""Parsing a source PDF's pages with pdfminer.six, treating the file as untrusted
(RFL-R2, RFL-R3, RFL-R5, RFL-R6).

pdfminer only lays pages out: it never runs JavaScript or actions, never follows links
and never fetches anything an external stream names. What it would decode is checked
first: every content stream (pages and form XObjects alike) is decoded with every stage
bounded by the decompressed stream size limit before pdfminer decodes it, and every
image is held to the pixel limit by the dimensions it declares (images are never
decoded here).
"""

import io
import logging
import zlib
from collections.abc import Iterator, Sequence
from contextlib import AbstractContextManager
from pathlib import Path
from types import TracebackType
from typing import BinaryIO

from pdfminer.ascii85 import ascii85decode, asciihexdecode
from pdfminer.converter import PDFPageAggregator
from pdfminer.layout import LAParams, LTContainer, LTImage, LTItem, LTPage
from pdfminer.lzw import LZWDecoder
from pdfminer.pdfdocument import PDFDocument, PDFXRefFallback
from pdfminer.pdfinterp import PDFPageInterpreter, PDFResourceManager
from pdfminer.pdfpage import PDFPage
from pdfminer.pdfparser import PDFParser
from pdfminer.pdftypes import (
    LITERALS_ASCII85_DECODE,
    LITERALS_ASCIIHEX_DECODE,
    LITERALS_FLATE_DECODE,
    LITERALS_LZW_DECODE,
    LITERALS_RUNLENGTH_DECODE,
    PDFStream,
    resolve1,
)
from pdfminer.psexceptions import PSException
from pdfminer.runlength import rldecode

from pdf2epub.reflow.limits import (
    ResourceLimitExceeded,
    check_image,
    check_stream_size,
    inflate,
    join_bounded,
    run_length_size,
)
from pdf2epub.reflow.source import CorruptPdf

log = logging.getLogger(__name__)


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
            except (PSException, zlib.error) as error:  # pdfminer catches zlib.error today
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
    """Decode ``stream`` as pdfminer would, but bounded at every stage. A stage that
    fails is left for pdfminer to handle as it does; filters that never make a content
    stream bigger (image codecs) end the check."""
    if stream.rawdata is None:  # already decoded (and checked) once
        return
    data = stream.rawdata
    check_stream_size(len(data))
    try:
        if stream.decipher and stream.objid is not None and stream.genno is not None:
            data = stream.decipher(stream.objid, stream.genno, data, stream.attrs)
        for name, _ in stream.get_filters():
            if name in LITERALS_FLATE_DECODE:
                data = inflate(data)
            elif name in LITERALS_LZW_DECODE:
                data = join_bounded(LZWDecoder(io.BytesIO(data)).run())
            elif name in LITERALS_RUNLENGTH_DECODE:
                check_stream_size(run_length_size(data))
                data = rldecode(data)
            elif name in LITERALS_ASCII85_DECODE:
                data = ascii85decode(data)
            elif name in LITERALS_ASCIIHEX_DECODE:
                data = asciihexdecode(data)
            else:
                return
            check_stream_size(len(data))
    except ResourceLimitExceeded:
        raise
    except Exception:  # a broken stage: pdfminer decodes (or rejects) it its own way
        log.debug("could not pre-check a content stream", exc_info=True)


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
