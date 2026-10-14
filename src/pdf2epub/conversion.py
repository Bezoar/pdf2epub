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
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Protocol

from pdf2epub.access import AccessDenied, unlock
from pdf2epub.cancel import CancelToken
from pdf2epub.epub import write_epub
from pdf2epub.issues import Issue, IssueCode, derive_outcome
from pdf2epub.options import ConversionOptions
from pdf2epub.passwords import Candidate
from pdf2epub.reflow.build import build_document
from pdf2epub.reflow.cover import book_cover
from pdf2epub.reflow.extract import PageText, read_pages
from pdf2epub.reflow.images import read_images
from pdf2epub.reflow.limits import ResourceLimitExceeded
from pdf2epub.reflow.parse import ParsedPdf
from pdf2epub.reflow.source import CorruptPdf, open_source
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


class _Cancelled(Exception):
    pass


class _Empty(Exception):
    """The PDF has no pages, or none yields any content (RFL-R4, RFL-R35)."""


_REPAIRED = (
    "The PDF is damaged: its cross-reference table was rebuilt by scanning the file, "
    "so the book may be incomplete."
)


def convert(
    planned: PlannedConversion,
    options: ConversionOptions,
    reporter: Reporter,
    cancel: CancelToken | None = None,
    candidates: Sequence[Candidate] = (),
) -> ConversionResult:
    """Convert ``planned``. If the source is password-protected, ``candidates`` are the
    passwords that may open it, in trial order (PWD-R12)."""
    started = time.monotonic()
    issues: list[Issue] = []
    output: str | None = None
    page_count: int | None = None
    password_source: str | None = None

    def add(issue: Issue) -> None:
        issues.append(issue)
        reporter.issue(issue)

    try:
        assert planned.destination is not None, "a conversion that runs has a destination"
        source_path, destination = Path(planned.source), Path(planned.destination)

        log.debug("conversion %d: opening %s", planned.id, source_path)
        access = unlock(source_path, candidates)
        password_source = access.source
        source = open_source(source_path, access.password)
        page_count = source.page_count
        log.debug("conversion %d: %d pages", planned.id, page_count)
        with ParsedPdf(source_path, access.password) as pdf:
            repaired = pdf.repaired
            source = replace(source, xmp=pdf.xmp())
            reporter.progress("open", 1, 1)
            if page_count == 0:
                raise _Empty("The PDF has no pages.")

            pages: list[PageText] = []
            for page in read_pages(pdf):
                pages.append(page)
                reporter.progress("analyse", len(pages), page_count, page=page.page)

        images = read_images(source_path, access.password)
        # RFL-R35: checked before anything else can add an issue (repaired_pdf included),
        # so empty_document is the only one. A page's content is its text and its book
        # images.
        if not any(page.lines for page in pages) and not images:
            raise _Empty("No page of the PDF has any text or image.")
        if access.owner_password_used:
            add(
                Issue(
                    IssueCode.OWNER_PASSWORD_USED,
                    f"converted using owner password from {access.source}",
                )
            )
        if repaired:
            add(Issue(IssueCode.REPAIRED_PDF, _REPAIRED))

        document, found = build_document(source, pages, images, options, access.password)
        for issue in found:
            add(issue)
        document = replace(document, cover=book_cover(options.cover, source_path, access.password))
        reporter.progress("reflow", 1, 1)

        write_atomically(write_epub(document), destination, cancel)
        output = str(destination)
        reporter.progress("write", 1, 1)
        log.info("converted %s to %s", source_path, destination)
    except AccessDenied as error:
        add(error.issue)
    except CorruptPdf as error:
        add(Issue(IssueCode.CORRUPT_PDF, str(error)))
    except _Empty as error:
        add(Issue(IssueCode.EMPTY_DOCUMENT, str(error)))
    except ResourceLimitExceeded as error:
        pages_hit = [error.page] if error.page is not None else []
        add(Issue(IssueCode.RESOURCE_LIMIT, str(error), pages=pages_hit))
    except _WriteFailed as error:
        add(Issue(IssueCode.WRITE_FAILED, str(error)))
    except _Cancelled:
        # BAT-R17: the conversion running when the batch is cancelled is not attempted.
        add(Issue(IssueCode.NOT_ATTEMPTED, "The batch was interrupted during this conversion."))
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
        password_source=password_source,
        pages=page_count,
        duration=round(time.monotonic() - started, 3),
        ocr=None,
    )


def write_atomically(data: bytes, destination: Path, cancel: CancelToken | None = None) -> None:
    """Write ``data`` to a hidden temporary file beside ``destination``, then rename it
    over the destination (BAT-R13), unless ``cancel`` is set by then. The temporary file
    never outlives a failure or a cancellation, and an existing destination is untouched
    by either (BAT-R14)."""
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
        if cancel is not None and cancel.cancelled:
            raise _Cancelled
        os.replace(temporary, destination)
    except OSError as error:
        Path(temporary).unlink(missing_ok=True)
        raise _WriteFailed(f"Could not write {destination}: {error.strerror or error}") from error
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise
