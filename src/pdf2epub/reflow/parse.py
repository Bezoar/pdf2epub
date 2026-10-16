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
from typing import BinaryIO, ClassVar

from pdfminer.ascii85 import ascii85decode, asciihexdecode
from pdfminer.ccitt import ccittfaxdecode
from pdfminer.converter import PDFPageAggregator
from pdfminer.layout import (
    LAParams,
    LTChar,
    LTComponent,
    LTContainer,
    LTImage,
    LTItem,
    LTPage,
)
from pdfminer.lzw import LZWDecoder
from pdfminer.pdfcolor import PDFColorSpace
from pdfminer.pdfdocument import (
    PDFBaseXRef,
    PDFDocument,
    PDFNoValidXRef,
    PDFStandardSecurityHandler,
    PDFStandardSecurityHandlerV5,
    PDFXRef,
    PDFXRefFallback,
    PDFXRefStream,
)
from pdfminer.pdffont import PDFFont
from pdfminer.pdfinterp import PDFGraphicState, PDFPageInterpreter, PDFResourceManager
from pdfminer.pdfpage import PDFPage
from pdfminer.pdfparser import PDFParser, PDFSyntaxError
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
    int_value,
    resolve1,
)
from pdfminer.psexceptions import PSEOF, PSException
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

    def __init__(
        self, path: Path, password: Secret | None = None, page_count: int | None = None
    ) -> None:
        """Open ``path``. With ``page_count``, the number of pages pdfium found, a page
        tree that reads differently here is damage: the cross-reference table is rebuilt
        by scanning the file (RFL-R37). If the two still disagree, the reading that
        shares more pages with pdfium's is kept, the rebuilt one on a tie, and
        ``page_count`` says how many pages it has."""
        self._file: BinaryIO = path.open("rb")
        self.page_count: int | None = None
        """The pages read here, when ``page_count`` was given; else None."""
        self._unparseable: set[int] = set()
        try:
            self._document = self._open(password, rebuild=False)
            if page_count is None:
                return
            found = self._count()
            if found != page_count and not self.repaired:
                first = self._document, found
                self._document = self._open(password, rebuild=True)
                found = self._count()
                if found != page_count and _shared(first[1], page_count) > _shared(
                    found, page_count
                ):
                    self._document, found = first
            if found is None:
                raise CorruptPdf("The PDF's page tree can't be read, even with repair")
            self.page_count = found
        except BaseException:
            self._file.close()
            raise

    def _open(self, password: Secret | None, rebuild: bool) -> "_Document":
        try:
            return _Document(
                PDFParser(self._file),
                password=password.reveal() if password is not None else "",
                rebuild=rebuild,
            )
        except (PSException, RecursionError) as error:
            raise CorruptPdf(f"The PDF can't be parsed, even with repair: {error}") from error

    def _count(self) -> int | None:
        """The number of pages in the page tree, or None when it can't be read."""
        try:
            return sum(1 for _ in self.pages())
        except CorruptPdf:
            return None

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
        except (PSException, RecursionError) as error:
            raise CorruptPdf(f"The PDF's page tree can't be read: {error}") from error

    def layouts(self, laparams: LAParams) -> Iterator[tuple[int, LTPage]]:
        """Each page's 1-based index and layout, in order. A page that can't be parsed
        is skipped and added to ``unparseable`` (RFL-R37); the pages after it are still
        read. Raises ``ResourceLimitExceeded`` naming the page where a limit is hit."""
        manager = PDFResourceManager(caching=True)
        device = _StyledAggregator(manager, laparams=laparams)
        interpreter = _GuardedInterpreter(manager, device)
        for number, page in enumerate(self.pages(), start=1):
            try:
                interpreter.process_page(page)
                layout = device.get_result()
                _check_images(layout)
                _to_visible(layout, page)
            except ResourceLimitExceeded as error:
                raise error.on_page(number) from None
            # pdfminer catches zlib.error today; RecursionError: damage that loops or
            # nests too deep (RFL-R37)
            except (PSException, RecursionError, zlib.error) as error:
                log.debug("page %d can't be parsed: %s", number, error)
                self._unparseable.add(number)
                # A page given up part-way may leave the device mid-page: start afresh.
                device = _StyledAggregator(manager, laparams=laparams)
                interpreter = _GuardedInterpreter(manager, device)
                continue
            yield number, layout

    @property
    def unparseable(self) -> frozenset[int]:
        """The 1-based pages ``layouts`` has found it can't parse so far (RFL-R37)."""
        return frozenset(self._unparseable)

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self._file.close()


def _to_visible(layout: LTPage, page: PDFPage) -> None:
    """Move ``layout`` into the visible page's frame: its CropBox (cut to its MediaBox),
    turned as ``/Rotate`` says, with the origin at its bottom-left corner. pdfminer lays a
    page out on its MediaBox; PDFium renders, and book images are placed on, the visible
    page (RFL-R9)."""
    media = page.mediabox
    crop = page.cropbox
    box = (
        max(crop[0], media[0]),
        max(crop[1], media[1]),
        min(crop[2], media[2]),
        min(crop[3], media[3]),
    )
    if box[2] <= box[0] or box[3] <= box[1] or tuple(box) == tuple(media):
        return
    # The same turn and shift pdfminer's interpreter applies to the MediaBox.
    x0, y0, x1, y1 = media
    a, b, c, d, e, f = {
        90: (0, -1, 1, 0, -y0, x1),
        180: (-1, 0, 0, -1, x1, y1),
        270: (0, 1, -1, 0, y1, -x0),
    }.get(page.rotate, (1, 0, 0, 1, -x0, -y0))
    xs, ys = zip(
        *((a * x + c * y + e, b * x + d * y + f) for x in box[0::2] for y in box[1::2]),
        strict=True,
    )
    dx, dy = min(xs), min(ys)
    stack: list[LTItem] = [layout]
    while stack:
        item = stack.pop()
        if isinstance(item, LTComponent):
            left, bottom, right, top = item.bbox
            item.set_bbox((left - dx, bottom - dy, right - dx, top - dy))
        if isinstance(item, LTContainer):
            stack.extend(item)
    layout.set_bbox((0, 0, max(xs) - dx, max(ys) - dy))


def _shared(found: int | None, page_count: int) -> int:
    """How many pages a reading of ``found`` pages has in common with pdfium's
    ``page_count``, matched by position."""
    return min(found or 0, page_count)


class _SecurityHandlerV5(PDFStandardSecurityHandlerV5):
    """The AES-256 (R5, R6) Standard security handler, reading only the first 48 bytes of
    ``/O`` and ``/U``, the length ISO 32000-2 gives them. Some writers pad both to 127
    bytes (qpdf's test files among them); pdfminer.six hashed the whole ``/U`` into the
    owner-password check, so it refused the right owner password (#87)."""

    def init_params(self) -> None:
        super().init_params()
        # Recompute every part the base class cut from the untruncated strings: R5 hashes
        # the whole key salt, so the padding must not reach it.
        self.o, self.u = self.o[:48], self.u[:48]
        self.o_hash, self.o_validation_salt, self.o_key_salt = (
            self.o[:32],
            self.o[32:40],
            self.o[40:],
        )
        self.u_hash, self.u_validation_salt, self.u_key_salt = (
            self.u[:32],
            self.u[32:40],
            self.u[40:],
        )


class _Document(PDFDocument):
    """pdfminer's document, guarded against damage that would otherwise recurse without
    end (#94): a chain of cross-reference sections that loops back on itself is rebuilt
    by scanning the file (RFL-R3), and an object stored inside itself is not found.
    ``rebuild`` skips the cross-reference table and rebuilds it straight away."""

    security_handler_registry: ClassVar[dict[int, type[PDFStandardSecurityHandler]]] = {
        **PDFDocument.security_handler_registry,
        5: _SecurityHandlerV5,
    }

    def __init__(self, parser: PDFParser, password: str = "", rebuild: bool = False) -> None:
        self._rebuild = rebuild
        self._resolving: set[int] = set()
        """The objects being read, each inside the one before (an object stream holds
        its objects): one asked for again while it is still being read is a loop."""
        super().__init__(parser, password=password)

    def read_xref_from(self, parser: PDFParser, start: int, xrefs: list[PDFBaseXRef]) -> None:
        """Read the section at ``start`` and every section it leads to, in pdfminer's
        order (a section's ``/XRefStm`` before its ``/Prev``), with a loop instead of
        recursion, so no chain of incremental updates can exhaust the stack. A section
        reached twice is damage: ``PDFNoValidXRef`` makes pdfminer rebuild the table."""
        if self._rebuild:
            raise PDFNoValidXRef("the cross-reference table is rebuilt by scanning the file")
        pending, seen = [start], set()
        while pending:
            position = pending.pop()
            if position in seen:
                raise PDFNoValidXRef(f"the cross-reference sections loop back to {position}")
            seen.add(position)
            trailer = _read_xref_section(parser, position, xrefs)
            # Last in, first out: /XRefStm (and all it leads to) is read before /Prev.
            for key in ("Prev", "XRefStm"):
                if key in trailer:
                    pending.append(int_value(trailer[key]))

    def getobj(self, objid: int) -> object:
        if objid in self._resolving:
            raise PDFSyntaxError(f"object {objid} is stored inside itself")
        self._resolving.add(objid)
        try:
            return super().getobj(objid)
        finally:
            self._resolving.discard(objid)


def _read_xref_section(
    parser: PDFParser, start: int, xrefs: list[PDFBaseXRef]
) -> dict[str, object]:
    """Read the one cross-reference section (table or stream) at ``start`` into
    ``xrefs``, as ``PDFDocument.read_xref_from`` does, and return its trailer."""
    parser.seek(start)
    parser.reset()
    try:
        position, token = parser.nexttoken()
    except PSEOF as error:
        raise PDFNoValidXRef("Unexpected EOF") from error
    xref: PDFBaseXRef
    if isinstance(token, int):  # a cross-reference stream (PDF 1.5)
        parser.seek(position)
        parser.reset()
        xref = PDFXRefStream()
    else:
        if token is parser.KEYWORD_XREF:
            parser.nextline()
        xref = PDFXRef()
    xref.load(parser)
    xrefs.append(xref)
    return xref.get_trailer()


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
