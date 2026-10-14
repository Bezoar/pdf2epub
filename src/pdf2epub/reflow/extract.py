"""Per-page text extraction and layout grouping with pdfminer.six (RFL-R1, RFL-R10).

The walking skeleton keeps pdfminer's own grouping: each text box on a page becomes one
block, its lines joined with a single space (RFL-R19).
"""

import re
import unicodedata
from collections.abc import Iterator
from dataclasses import dataclass

from pdfminer.layout import LAParams, LTTextContainer, LTTextLine

from pdf2epub.reflow.parse import ParsedPdf

# Characters XML 1.0 does not allow, which a text layer can still carry.
_NOT_XML = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f￾￿\ud800-\udfff]")


@dataclass(frozen=True)
class PageText:
    """The text blocks of one page, in reading order."""

    page: int
    """1-based PDF page index."""
    blocks: list[str]


def normalise(text: str) -> str:
    """Unicode NFC, without characters that XML can't carry (RFL-R8, in part)."""
    return _NOT_XML.sub("", unicodedata.normalize("NFC", text))


def read_pages(pdf: ParsedPdf) -> Iterator[PageText]:
    """Yield each page's text blocks, one page at a time."""
    for number, layout in enumerate(pdf.layouts(LAParams()), start=1):
        blocks: list[str] = []
        for element in layout:
            if not isinstance(element, LTTextContainer):
                continue
            lines = [line.get_text().strip() for line in element if isinstance(line, LTTextLine)]
            text = normalise(" ".join(line for line in lines if line))
            if text.strip():
                blocks.append(" ".join(text.split()))
        yield PageText(page=number, blocks=blocks)
