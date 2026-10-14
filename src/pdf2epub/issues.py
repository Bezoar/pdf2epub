"""Issues, their codes and severities, and outcomes (API §6).

Each ``IssueCode`` has a fixed severity, taken from the registry in API §6.1 (API-R10).
When an issue fires is owned by the spec the registry names for it.
"""

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class Severity(StrEnum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class Outcome(StrEnum):
    CONVERTED = "converted"
    SKIPPED = "skipped"
    FAILED = "failed"


class IssueCode(StrEnum):
    MISSING_PASSWORD = "missing_password"
    WRONG_PASSWORD = "wrong_password"
    RESTRICTED = "restricted"
    DRM_PROTECTED = "drm_protected"
    UNSUPPORTED_ENCRYPTION = "unsupported_encryption"
    OWNER_PASSWORD_USED = "owner_password_used"
    NOT_FOUND = "not_found"
    NOT_A_PDF = "not_a_pdf"
    CORRUPT_PDF = "corrupt_pdf"
    REPAIRED_PDF = "repaired_pdf"
    EMPTY_DOCUMENT = "empty_document"
    RESOURCE_LIMIT = "resource_limit"
    OUTPUT_EXISTS = "output_exists"
    OUTPUT_COLLISION = "output_collision"
    WRITE_FAILED = "write_failed"
    PAGE_FALLBACK = "page_fallback"
    LANGUAGE_DEFAULTED = "language_defaulted"
    PAGE_SEQUENCE_GAP = "page_sequence_gap"
    OCR_UNAVAILABLE = "ocr_unavailable"
    OCR_TIMEOUT = "ocr_timeout"
    OCR_FAILED = "ocr_failed"
    TEXT_LAYER_REJECTED = "text_layer_rejected"
    NOT_ATTEMPTED = "not_attempted"
    TIMEOUT = "timeout"
    INTERNAL_ERROR = "internal_error"

    @property
    def severity(self) -> Severity:
        return SEVERITIES[self]


_E, _W, _I = Severity.ERROR, Severity.WARNING, Severity.INFO
SEVERITIES: dict[IssueCode, Severity] = {
    IssueCode.MISSING_PASSWORD: _E,
    IssueCode.WRONG_PASSWORD: _E,
    IssueCode.RESTRICTED: _E,
    IssueCode.DRM_PROTECTED: _E,
    IssueCode.UNSUPPORTED_ENCRYPTION: _E,
    IssueCode.OWNER_PASSWORD_USED: _I,
    IssueCode.NOT_FOUND: _E,
    IssueCode.NOT_A_PDF: _E,
    IssueCode.CORRUPT_PDF: _E,
    IssueCode.REPAIRED_PDF: _W,
    IssueCode.EMPTY_DOCUMENT: _E,
    IssueCode.RESOURCE_LIMIT: _E,
    IssueCode.OUTPUT_EXISTS: _I,
    IssueCode.OUTPUT_COLLISION: _I,
    IssueCode.WRITE_FAILED: _E,
    IssueCode.PAGE_FALLBACK: _W,
    IssueCode.LANGUAGE_DEFAULTED: _W,
    IssueCode.PAGE_SEQUENCE_GAP: _W,
    IssueCode.OCR_UNAVAILABLE: _W,
    IssueCode.OCR_TIMEOUT: _W,
    IssueCode.OCR_FAILED: _W,
    IssueCode.TEXT_LAYER_REJECTED: _I,
    IssueCode.NOT_ATTEMPTED: _I,
    IssueCode.TIMEOUT: _E,
    IssueCode.INTERNAL_ERROR: _E,
}

# Codes whose presence (without an error) makes the outcome `skipped` (API-R12).
SKIPPING = frozenset({IssueCode.OUTPUT_EXISTS, IssueCode.OUTPUT_COLLISION, IssueCode.NOT_ATTEMPTED})


@dataclass(frozen=True)
class Issue:
    """A named kind of problem attached to one conversion."""

    code: IssueCode
    message: str
    pages: list[int] = field(default_factory=list)
    reason: str | None = None
    hint: str | None = None

    @property
    def severity(self) -> Severity:
        """Always the code's fixed severity (API-R10)."""
        return self.code.severity

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": str(self.code),
            "severity": str(self.severity),
            "pages": list(self.pages),
            "reason": self.reason,
            "message": self.message,
            "hint": self.hint,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Issue":
        """The issue whose wire form (``to_dict``) is ``data``."""
        return cls(
            code=IssueCode(data["code"]),
            message=str(data["message"]),
            pages=[int(page) for page in data["pages"]],
            reason=None if data["reason"] is None else str(data["reason"]),
            hint=None if data["hint"] is None else str(data["hint"]),
        )


def derive_outcome(issues: list[Issue]) -> Outcome:
    """A conversion's outcome from its issues, in the order API-R12 gives."""
    if any(issue.severity is Severity.ERROR for issue in issues):
        return Outcome.FAILED
    if any(issue.code in SKIPPING for issue in issues):
        return Outcome.SKIPPED
    return Outcome.CONVERTED
