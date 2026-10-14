"""The ``OcrEngine`` protocol (OCR-R11, OCR-R12, OCR-R13) and the values it trades in.

An engine recognises one cleaned page image per call and returns word-level results:
lines of words, each word with its box and confidence. Boxes and line heights are in
pixels of the request's image, origin top-left; the pipeline maps them onto the page.
The pipeline, not the engine, computes coverage (OCR-R16) and records the attempts.

v1 has one adapter, for Tesseract (``ocr.tesseract``). ``load_engine`` is the one place
the core gets its engine from; there is no registry and no engine-selection option.

The run's preflight probes the engine once (``probe_engine``, OCR-R24): whether it is
there, which languages it has and which options it takes. The ``EngineProbe`` it returns
travels to each conversion, worker subprocesses included, so nothing probes again.

An attempt that runs past its deadline raises ``EngineTimeout``; one where the engine
crashes or reports an error raises ``EngineFailed`` (OCR-R22, OCR-R23). Either costs the
page, never the conversion.
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


class EngineTimeout(Exception):
    """The attempt was stopped at its deadline (OCR-R22)."""


class EngineFailed(Exception):
    """The engine crashed or exited with an error on the attempt (OCR-R23)."""


class OcrEngine(Protocol):
    """An OCR engine (OCR-R11)."""

    def capabilities(self) -> Capabilities:
        raise NotImplementedError  # pragma: no cover

    def recognise(self, request: OcrRequest) -> OcrPageResult:
        raise NotImplementedError  # pragma: no cover


@dataclass(frozen=True)
class EngineProbe:
    """What the run's preflight found out about the OCR engine (OCR-R24, OCR-R25)."""

    engine: OcrEngine | None
    """The engine, its capabilities already asked; None when it is missing."""
    languages: frozenset[str] | None = None
    """The languages it has data for; None when the engine doesn't say (any is taken)."""
    parameters: frozenset[str] | None = None
    """The names of the options it takes; None when not asked (no engine options were
    given) or when it couldn't say."""

    def missing(self, languages: str) -> list[str]:
        """The languages in ``languages`` (e.g. ``eng+deu``) the engine has no data for."""
        if self.languages is None:
            return []
        return [code for code in languages.split("+") if code not in self.languages]


def probe_engine(options: OcrOptions) -> EngineProbe:
    """Probe the OCR engine ``options`` name, once per run: Tesseract, from
    ``options.tesseract_path`` or else ``PATH`` (OCR-R24). It lists the engine's options
    only when ``options.engine_options`` has some to check (OCR-R25)."""
    from pdf2epub.ocr.tesseract import Tesseract

    engine = load_engine(options)
    if not isinstance(engine, Tesseract):
        return EngineProbe(engine)
    return EngineProbe(
        engine,
        engine.languages(),
        engine.parameters() if options.engine_options else None,
    )


def load_engine(options: OcrOptions) -> OcrEngine | None:
    """The OCR engine to use under ``options``: Tesseract, from ``options.tesseract_path``
    or else ``PATH``. None when that program isn't there; pages that would be OCR'd then
    keep what they have."""
    from pdf2epub.ocr.tesseract import find_tesseract

    return find_tesseract(options)
