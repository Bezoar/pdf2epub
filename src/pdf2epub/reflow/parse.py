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
import re
import zlib
from collections.abc import Iterator, Sequence
from contextlib import AbstractContextManager
from pathlib import Path
from types import TracebackType
from typing import BinaryIO

from pdfminer.ascii85 import ascii85decode, asciihexdecode
from pdfminer.ccitt import ccittfaxdecode
from pdfminer.converter import PDFPageAggregator
from pdfminer.layout import LAParams, LTChar, LTContainer, LTImage, LTItem, LTPage
from pdfminer.lzw import LZWDecoder
from pdfminer.pdfcolor import PDFColorSpace
from pdfminer.pdfdocument import PDFDocument, PDFXRefFallback
from pdfminer.pdffont import PDFFont
from pdfminer.pdfinterp import PDFGraphicState, PDFPageInterpreter, PDFResourceManager
from pdfminer.pdfpage import PDFPage
from pdfminer.pdfparser import PDFParser
from pdfminer.pdftypes import (
    LITERALS_ASCII85_DECODE,
    LITERALS_ASCIIHEX_DECODE,
    LITERALS_CCITTFAX_DECODE,
    LITERALS_DCT_DECODE,
    LITERALS_FLATE_DECODE,
    LITERALS_JBIG2_DECODE,
    LITERALS_JPX_DECODE,
    LITERALS_LZW_DECODE,
    LITERALS_RUNLENGTH_DECODE,
    PDFStream,
    resolve1,
)
from pdfminer.psexceptions import PSException
from pdfminer.runlength import rldecode
from pdfminer.utils import Matrix

from pdf2epub.passwords import Secret
from pdf2epub.reflow.limits import (
    MAX_STREAM_BYTES,
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

    def __init__(self, path: Path, password: Secret | None = None) -> None:
        self._file: BinaryIO = path.open("rb")
        try:
            self._document = PDFDocument(
                PDFParser(self._file), password=password.reveal() if password is not None else ""
            )
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

    def xmp(self) -> bytes | None:
        """The catalog's XMP metadata packet, decoded within the stream size limit, or
        None when there is none or it can't be read."""
        try:
            stream = resolve1(self._document.catalog.get("Metadata"))
            if not isinstance(stream, PDFStream):
                return None
            _check_stream(stream)
            data = stream.get_data()
        except ResourceLimitExceeded:
            raise
        except Exception:  # damaged metadata costs the metadata, never the book
            log.debug("the XMP metadata can't be read; it is ignored", exc_info=True)
            return None
        return data if isinstance(data, bytes) else None

    def pages(self) -> Iterator[PDFPage]:
        try:
            yield from PDFPage.create_pages(self._document)
        except PSException as error:
            raise CorruptPdf(f"The PDF's page tree can't be read: {error}") from error

    def layouts(self, laparams: LAParams) -> Iterator[LTPage]:
        """Each page's layout, in order. Raises ``ResourceLimitExceeded`` naming the page
        where a limit is hit, and ``CorruptPdf`` if a page can't be parsed."""
        manager = PDFResourceManager(caching=True)
        device = _StyledAggregator(manager, laparams=laparams)
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


# Font flags (PDF 32000-1 9.8.2) and font-name style suffixes (RFL-R22).
_ITALIC_FLAG, _FORCE_BOLD_FLAG = 1 << 6, 1 << 18
_BOLD_WEIGHT = 600
_BOLD_NAME = re.compile(r"bold|black|heavy|demi|semibold", re.IGNORECASE)
_ITALIC_NAME = re.compile(r"italic|oblique|[-,](?:it|ital)$", re.IGNORECASE)
STYLE = "pdf2epub_style"
"""The attribute every ``LTChar`` this module lays out carries: ``(bold, italic)``."""


def font_style(font: PDFFont) -> tuple[bool, bool]:
    """``(bold, italic)`` for ``font``, from its descriptor's flags, weight and italic
    angle, and from the style suffix of its name (``Times-BoldItalic``, ``Arial,Bold``,
    ``MinionPro-It``)."""
    descriptor = font.descriptor if isinstance(font.descriptor, dict) else {}
    flags = _number(descriptor.get("Flags"))
    weight = _number(descriptor.get("FontWeight"))
    angle = _number(descriptor.get("ItalicAngle"))
    name = str(font.fontname).split("+", 1)[-1]
    bold = bool(flags & _FORCE_BOLD_FLAG) or weight >= _BOLD_WEIGHT or bool(_BOLD_NAME.search(name))
    italic = bool(flags & _ITALIC_FLAG) or angle != 0 or bool(_ITALIC_NAME.search(name))
    return bold, italic


def _number(value: object) -> int:
    value = resolve1(value)
    if isinstance(value, int | float) and not isinstance(value, bool):
        return int(value)
    return 0


class _StyledAggregator(PDFPageAggregator):
    """Marks every character with its font's bold and italic style (``STYLE``)."""

    def __init__(self, manager: PDFResourceManager, laparams: LAParams) -> None:
        super().__init__(manager, laparams=laparams)
        self._styles: dict[int, tuple[PDFFont, tuple[bool, bool]]] = {}
        """Each font's style, by ``id`` (the font is kept here, so the id stays its own)."""

    def render_char(
        self,
        matrix: Matrix,
        font: PDFFont,
        fontsize: float,
        scaling: float,
        rise: float,
        cid: int,
        ncs: PDFColorSpace,
        graphicstate: PDFGraphicState,
    ) -> float:
        advance = super().render_char(matrix, font, fontsize, scaling, rise, cid, ncs, graphicstate)
        char = self.cur_item._objs[-1]
        if isinstance(char, LTChar):
            known = self._styles.get(id(font))
            if known is None:
                known = self._styles[id(font)] = (font, font_style(font))
            setattr(char, STYLE, known[1])
        return advance


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
        for name, params in stream.get_filters():
            if name in LITERALS_FLATE_DECODE:
                data = inflate(data)
            elif name in LITERALS_LZW_DECODE:
                data = join_bounded(LZWDecoder(io.BytesIO(data)).run())
            elif name in LITERALS_RUNLENGTH_DECODE:
                check_stream_size(run_length_size(data))
                data = rldecode(data)
            elif name in LITERALS_ASCII85_DECODE:
                # Every 5 bytes make at most 4, but "z" alone makes 4 zero bytes.
                check_stream_size(len(data) + 3 * data.count(b"z"))
                data = ascii85decode(data)
            elif name in LITERALS_ASCIIHEX_DECODE:
                data = asciihexdecode(data)
            elif name in _PASSED_THROUGH:
                pass  # pdfminer leaves the data as it is; later stages still count
            elif name in LITERALS_CCITTFAX_DECODE:
                check_stream_size(_ccitt_size(params))
                data = ccittfaxdecode(data, params)
            else:
                return  # pdfminer refuses the stream (unsupported filter): nothing to decode
            check_stream_size(len(data))
    except ResourceLimitExceeded:
        raise
    except Exception:  # a broken stage: pdfminer decodes (or rejects) it its own way
        log.debug("could not pre-check a content stream", exc_info=True)


_PASSED_THROUGH = (*LITERALS_DCT_DECODE, *LITERALS_JBIG2_DECODE, *LITERALS_JPX_DECODE)


def _ccitt_size(params: object) -> int:
    """The most bytes ``/CCITTFaxDecode`` can make: one bit per pixel of the declared
    size. Without a declared row count it can't be bounded, so it counts as too big."""
    params = resolve1(params)
    if not isinstance(params, dict):
        params = {}
    columns = _dimension(params.get("Columns", 1728))
    rows = _dimension(params.get("Rows"))
    if not rows:
        return MAX_STREAM_BYTES + 1
    return (columns + 7) // 8 * rows


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
