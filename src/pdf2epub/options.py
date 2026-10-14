"""Option classes (API-R9): frozen dataclasses of plain data, with every default defined
here, in the core. Front ends pass a field only when the user set it.

The meaning and default of each field belong to the owning spec: batch for
``DiscoveryOptions`` and ``BatchOptions`` (BAT-R23), reflow for ``ConversionOptions``
(RFL-R33) and ocr for ``OcrOptions``.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

Isolation = Literal["subprocess", "inprocess"]


@dataclass(frozen=True)
class DiscoveryOptions:
    """How ``plan_batch`` finds inputs and maps them to destinations."""

    recursive: bool = False
    output: Path | None = None


@dataclass(frozen=True)
class BatchOptions:
    """How ``run_batch`` runs the planned conversions."""

    timeout: int = 1800
    overwrite: bool = False
    isolation: Isolation = "subprocess"
    strict: bool = False


@dataclass(frozen=True)
class OcrOptions:
    """How pages are OCR'd."""

    mode: Literal["auto", "always", "never"] = "auto"
    languages: str | None = None
    quality: Literal["fast", "balanced", "best"] = "balanced"
    page_timeout: int = 180
    min_confidence: float | None = None
    engine_options: dict[str, str] = field(default_factory=dict)
    tesseract_path: Path | None = None
    tessdata_dir: Path | None = None


@dataclass(frozen=True)
class ConversionOptions:
    """How each PDF becomes a book."""

    mode: Literal["auto", "reflow"] = "auto"
    language: str | None = None
    title: str | None = None
    authors: list[str] | None = None
    cover: Literal["page1"] | Path | None = "page1"
    ocr: OcrOptions = field(default_factory=OcrOptions)
