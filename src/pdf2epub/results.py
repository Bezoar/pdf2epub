"""Conversion results and the batch report (API §7).

``to_dict`` gives each result's wire form: the fields of the ``conversion_finished`` and
``batch_finished`` events (API-R17, API-R19), with enums as their string values.
"""

from dataclasses import dataclass
from typing import Any

from pdf2epub.issues import Issue, Outcome


@dataclass(frozen=True)
class OcrSummary:
    engine: str
    engine_version: str
    languages: list[str]
    quality: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "engine": self.engine,
            "engine_version": self.engine_version,
            "languages": list(self.languages),
            "quality": self.quality,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "OcrSummary":
        return cls(
            engine=str(data["engine"]),
            engine_version=str(data["engine_version"]),
            languages=[str(language) for language in data["languages"]],
            quality=str(data["quality"]),
        )


@dataclass(frozen=True)
class ConversionResult:
    id: int
    source: str
    destination: str | None
    outcome: Outcome
    issues: list[Issue]
    output: str | None
    password_source: str | None
    pages: int | None
    duration: float
    ocr: OcrSummary | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "source": self.source,
            "destination": self.destination,
            "outcome": str(self.outcome),
            "issues": [issue.to_dict() for issue in self.issues],
            "output": self.output,
            "password_source": self.password_source,
            "pages": self.pages,
            "duration": self.duration,
            "ocr": None if self.ocr is None else self.ocr.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ConversionResult":
        """The result whose wire form (``to_dict``) is ``data``."""

        def optional_str(value: Any) -> str | None:
            return None if value is None else str(value)

        return cls(
            id=int(data["id"]),
            source=str(data["source"]),
            destination=optional_str(data["destination"]),
            outcome=Outcome(data["outcome"]),
            issues=[Issue.from_dict(issue) for issue in data["issues"]],
            output=optional_str(data["output"]),
            password_source=optional_str(data["password_source"]),
            pages=None if data["pages"] is None else int(data["pages"]),
            duration=float(data["duration"]),
            ocr=None if data["ocr"] is None else OcrSummary.from_dict(data["ocr"]),
        )


@dataclass(frozen=True)
class Totals:
    converted: int
    skipped: int
    failed: int

    def to_dict(self) -> dict[str, Any]:
        return {"converted": self.converted, "skipped": self.skipped, "failed": self.failed}


@dataclass(frozen=True)
class BatchReport:
    tool_version: str
    started_at: str
    conversions: list[ConversionResult]
    totals: Totals
    interrupted: bool
    exit_code: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool_version": self.tool_version,
            "started_at": self.started_at,
            "totals": self.totals.to_dict(),
            "interrupted": self.interrupted,
            "exit_code": self.exit_code,
            "conversions": [conversion.to_dict() for conversion in self.conversions],
        }
