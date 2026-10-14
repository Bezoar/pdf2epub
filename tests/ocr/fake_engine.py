"""A fake ``OcrEngine`` with scripted results, for tests at the ``OcrEngine`` seam.

The fake records every request it gets and answers the n-th call with ``script(n,
request)``. It reports itself as Tesseract, the only engine v1 has (OCR-R11).

``words_of`` scripts what a perfect engine would read off a scan of a born-digital
fixture: the words of that fixture's page, as pdfminer places them, mapped to pixels of
the page image. The words come from the fixture, never from pdf2epub.
"""

from collections.abc import Callable, Iterator
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

import pytest
from pdfminer.high_level import extract_pages
from pdfminer.layout import LTAnno, LTChar, LTTextContainer, LTTextLine

from pdf2epub.ocr.engine import Capabilities, OcrLine, OcrPageResult, OcrRequest, Word

CAPABILITIES = Capabilities(
    name="tesseract",
    version="5.3.4",
    granularities=("word", "line"),
    confidence_scale="0-100",
    osd=True,
    licence="Apache-2.0",
)
CONFIDENCE = 0.95

Script = Callable[[int, OcrRequest], OcrPageResult]


def no_words(call: int, request: OcrRequest) -> OcrPageResult:
    """An engine that never recognises anything."""
    return OcrPageResult(lines=())


@dataclass
class FakeEngine:
    script: Script = no_words
    requests: list[OcrRequest] = field(default_factory=list)

    def capabilities(self) -> Capabilities:
        return CAPABILITIES

    def recognise(self, request: OcrRequest) -> OcrPageResult:
        self.requests.append(request)
        return self.script(len(self.requests) - 1, request)


def install(monkeypatch: pytest.MonkeyPatch, engine: FakeEngine) -> FakeEngine:
    """Make ``engine`` the engine every conversion in this test gets."""

    def load_engine(options: Any) -> FakeEngine:
        return engine

    monkeypatch.setattr("pdf2epub.ocr.engine.load_engine", load_engine)
    return engine


def _pages(pdf: Path) -> Iterator[tuple[float, float, list[list[list[LTChar]]]]]:
    """Each page's width, height and text lines, each line as its words' glyphs."""
    for layout in extract_pages(pdf):
        lines: list[list[list[LTChar]]] = []
        for element in layout:
            if not isinstance(element, LTTextContainer):
                continue
            for item in element:
                if not isinstance(item, LTTextLine):
                    continue
                words: list[list[LTChar]] = [[]]
                for child in item:
                    if isinstance(child, LTChar) and not child.get_text().isspace():
                        words[-1].append(child)
                    elif isinstance(child, LTChar | LTAnno) and words[-1]:
                        words.append([])
                lines.append([word for word in words if word])
        yield layout.width, layout.height, lines


def words_of(pdf: Path, dpi: int, centre: Callable[[str], bool] = lambda text: False) -> Script:
    """A script that answers the n-th call with the words of page n + 1 of ``pdf`` (every
    page must be OCR'd, in order), with confidence ``CONFIDENCE``. A line for which
    ``centre(text)`` holds is moved to the middle of the page, as if set centred."""
    scale = dpi / 72
    pages: list[OcrPageResult] = []
    for width, height, glyph_lines in _pages(pdf):
        lines: list[OcrLine] = []
        for glyph_words in glyph_lines:
            words = [
                Word(
                    text="".join(c.get_text() for c in glyphs),
                    x0=min(c.x0 for c in glyphs) * scale,
                    top=(height - max(c.y1 for c in glyphs)) * scale,
                    x1=max(c.x1 for c in glyphs) * scale,
                    bottom=(height - min(c.y0 for c in glyphs)) * scale,
                    confidence=CONFIDENCE,
                    raw_confidence=CONFIDENCE * 100,
                )
                for glyphs in glyph_words
            ]
            if centre(" ".join(word.text for word in words)):
                shift = (width * scale - (words[-1].x1 - words[0].x0)) / 2 - words[0].x0
                words = [replace(word, x0=word.x0 + shift, x1=word.x1 + shift) for word in words]
            top, bottom = min(w.top for w in words), max(w.bottom for w in words)
            lines.append(OcrLine(tuple(words), bottom - top))
        pages.append(OcrPageResult(lines=tuple(lines)))

    def script(call: int, request: OcrRequest) -> OcrPageResult:
        return pages[call]

    return script
