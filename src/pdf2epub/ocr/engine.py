"""The ``OcrEngine`` protocol (OCR-R11, OCR-R12, OCR-R13) and the values it trades in.

An engine recognises one cleaned page image per call and returns word-level results:
lines of words, each word with its box and confidence. Boxes and line heights are in
pixels of the request's image, origin top-left; the pipeline maps them onto the page.
The pipeline, not the engine, computes coverage (OCR-R16) and records the attempts.

v1 has one adapter, for Tesseract (a later ticket). ``load_engine`` is the one place the
core gets its engine from; there is no registry and no engine-selection option.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal, Protocol

from PIL import Image

from pdf2epub.options import OcrOptions

LayoutHint = Literal["PAGE", "BLOCK", "LINE", "SPARSE"]


@dataclass(frozen=True)
class Capabilities:
    """What an engine is and can do (OCR-R11, OCR-R32)."""

    name: str
    """The engine's name, as the result's ``ocr.engine`` reports it."""
    version: str
    """The engine's version, as the result's ``ocr.engine_version`` reports it."""
    granularities: tuple[str, ...]
    """The levels results come in, e.g. ``("word", "line")``."""
    confidence_scale: str
    """How the engine's raw confidence reads, e.g. ``"0-100"``."""
    osd: bool
    """Whether the engine detects page orientation."""
    licence: str
    """The engine's licence, e.g. ``"Apache-2.0"``."""


@dataclass(frozen=True)
class OcrRequest:
    """One OCR attempt on one page (OCR-R12)."""

    image: Image.Image
    """The cleaned page image."""
    dpi: int
    languages: str
    """Tesseract language codes, e.g. ``eng+deu``."""
    layout_hint: LayoutHint
    deadline: float
    """The ``time.monotonic()`` value by which the attempt must finish."""
    engine_options: Mapping[str, str] = field(default_factory=dict)
    """Passed through to the engine, without their ``tesseract.`` namespace."""


@dataclass(frozen=True)
class Word:
    """A recognised word, its box in pixels of the request image (origin top-left)."""

    text: str
    x0: float
    top: float
    x1: float
    bottom: float
    confidence: float
    """Normalised to [0, 1]."""
    raw_confidence: float
    """As the engine gave it."""


@dataclass(frozen=True)
class OcrLine:
    """A recognised line of words, left to right."""

    words: tuple[Word, ...]
    height: float
    """The line's height in pixels, used to infer headings (RFL-R21)."""


@dataclass(frozen=True)
class Attempt:
    """One OCR attempt on a page: the variant run, and how it scored."""

    variant: str
    confidence: float
    coverage: float
    duration: float
    """Seconds."""


@dataclass(frozen=True)
class OcrPageResult:
    """What OCR found on one page (OCR-R13)."""

    lines: tuple[OcrLine, ...]
    coverage: float = 0.0
    """The share of the page's ink inside recognised words' boxes (OCR-R16); set by the
    pipeline."""
    warnings: tuple[str, ...] = ()
    """Engine diagnostics, as text."""
    attempts: tuple[Attempt, ...] = ()
    """One record per OCR attempt; set by the pipeline."""

    @property
    def words(self) -> list[Word]:
        return [word for line in self.lines for word in line.words]

    @property
    def page_confidence(self) -> float:
        """The mean word confidence, weighted by word length; 0 with no words."""
        words = self.words
        total = sum(len(word.text) for word in words)
        if total == 0:
            return 0.0
        return sum(word.confidence * len(word.text) for word in words) / total


class OcrEngine(Protocol):
    """An OCR engine (OCR-R11)."""

    def capabilities(self) -> Capabilities:
        raise NotImplementedError  # pragma: no cover

    def recognise(self, request: OcrRequest) -> OcrPageResult:
        raise NotImplementedError  # pragma: no cover


def load_engine(options: OcrOptions) -> OcrEngine | None:
    """The OCR engine to use under ``options``, or None when there is none.

    The Tesseract adapter comes with a later ticket; until then there is none, and pages
    that would be OCR'd keep what they have."""
    return None
