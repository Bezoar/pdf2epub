"""One conversion: a planned source PDF through the stages ``open``, ``analyse``,
``reflow`` and ``write`` (API-R21) to an EPUB at its destination.

The batch runner supplies a ``Reporter``, which turns progress and issues into events as
they happen. Whatever goes wrong, ``convert`` returns a result: an unexpected exception
becomes ``internal_error`` for this conversion only (BAT-R20).
"""

import logging
import os
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from pdf2epub.epub import write_epub
from pdf2epub.issues import Issue, IssueCode, derive_outcome
from pdf2epub.options import ConversionOptions
from pdf2epub.reflow.build import build_document
from pdf2epub.reflow.extract import PageText, read_pages
from pdf2epub.reflow.source import open_source
from pdf2epub.results import ConversionResult

log = logging.getLogger(__name__)

# The process umask, read once at import, so a written EPUB gets the permissions any new
# file would (mkstemp creates its file as 0600).
_UMASK = os.umask(0o022)
os.umask(_UMASK)


@dataclass(frozen=True)
class PlannedConversion:
    """One conversion in a ``BatchPlan`` (API-R2)."""

    id: int
    """Its 0-based index in the plan."""
    source: str
    """Absolute path of the source PDF."""
    destination: str | None
    """Absolute path the EPUB maps to, or None when none applies."""
    issues: list[Issue] = field(default_factory=list)
    """Issues found at planning time."""


class Reporter(Protocol):
    """Where a conversion reports progress and issues as they happen."""

    def progress(self, stage: str, done: int, of: int, **fields: Any) -> None: ...

    def issue(self, issue: Issue) -> None: ...


class _WriteFailed(Exception):
    pass


def convert(
    planned: PlannedConversion, options: ConversionOptions, reporter: Reporter
) -> ConversionResult:
    started = time.monotonic()
    issues: list[Issue] = []
    output: str | None = None
    page_count: int | None = None

    def add(issue: Issue) -> None:
        issues.append(issue)
        reporter.issue(issue)

    try:
        assert planned.destination is not None, "a conversion that runs has a destination"
        source_path, destination = Path(planned.source), Path(planned.destination)

        log.debug("conversion %d: opening %s", planned.id, source_path)
        source = open_source(source_path)
        page_count = source.page_count
        log.debug("conversion %d: %d pages", planned.id, page_count)
        reporter.progress("open", 1, 1)

        pages: list[PageText] = []
        for page in read_pages(source_path):
            pages.append(page)
            reporter.progress("analyse", len(pages), page_count, page=page.page)

        document, found = build_document(source, pages, options)
        for issue in found:
            add(issue)
        reporter.progress("reflow", 1, 1)

        write_atomically(write_epub(document), destination)
        output = str(destination)
        reporter.progress("write", 1, 1)
        log.info("converted %s to %s", source_path, destination)
    except _WriteFailed as error:
        add(Issue(IssueCode.WRITE_FAILED, str(error)))
    except Exception as error:
        log.debug("conversion %d failed unexpectedly", planned.id, exc_info=True)
        add(
            Issue(
                IssueCode.INTERNAL_ERROR,
                f"pdf2epub failed unexpectedly ({type(error).__name__}: {error}); "
                "please report this bug",
            )
        )

    return ConversionResult(
        id=planned.id,
        source=planned.source,
        destination=planned.destination,
        outcome=derive_outcome(issues),
        issues=issues,
        output=output,
        password_source=None,
        pages=page_count,
        duration=round(time.monotonic() - started, 3),
        ocr=None,
    )


def write_atomically(data: bytes, destination: Path) -> None:
    """Write ``data`` to a hidden temporary file beside ``destination``, then rename it
    over the destination (BAT-R13). The temporary file never outlives a failure."""
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        handle, temporary = tempfile.mkstemp(
            dir=destination.parent, prefix=f".{destination.name}.", suffix=".tmp"
        )
    except OSError as error:
        raise _WriteFailed(f"Could not write {destination}: {error.strerror or error}") from error
    try:
        with os.fdopen(handle, "wb") as file:
            os.fchmod(file.fileno(), 0o666 & ~_UMASK)
            file.write(data)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, destination)
    except OSError as error:
        Path(temporary).unlink(missing_ok=True)
        raise _WriteFailed(f"Could not write {destination}: {error.strerror or error}") from error
