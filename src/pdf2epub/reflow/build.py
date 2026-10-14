"""Building the document model from a source PDF and its page text (RFL-R25, RFL-R31,
RFL-R32, RFL-R34).

The walking skeleton makes one chapter holding every page: a page-break marker at the
start of each page, then that page's text blocks as paragraphs. Furniture removal, page
joins, headings, chapters from the outline, images and the cover come with later tickets.
"""

import re
import uuid
from datetime import UTC, datetime, timedelta, timezone

from pdf2epub.issues import Issue, IssueCode
from pdf2epub.options import ConversionOptions
from pdf2epub.reflow.extract import PageText, normalise
from pdf2epub.reflow.model import (
    Block,
    Chapter,
    Document,
    Metadata,
    PageBreak,
    Paragraph,
    Text,
    TocEntry,
)
from pdf2epub.reflow.source import SourcePdf

# Fixed once for pdf2epub: dc:identifier is urn:uuid: plus UUIDv5(this, the PDF's SHA-256).
IDENTIFIER_NAMESPACE = uuid.UUID("de933f19-549d-40b3-bd7c-840b7f360868")
DEFAULT_LANGUAGE = "en"
DEFAULT_MODIFIED = "1980-01-01T00:00:00Z"

_PDF_DATE = re.compile(
    r"^(?:D:)?(\d{4})(\d{2})?(\d{2})?(\d{2})?(\d{2})?(\d{2})?"
    r"(?:([Zz])|([+-])(\d{2})'?(\d{2})?'?)?"
)


def build_document(
    source: SourcePdf, pages: list[PageText], options: ConversionOptions
) -> tuple[Document, list[Issue]]:
    """The document model for ``source``, and the issues found while building it."""
    metadata, issues = _metadata(source, options)
    blocks: list[Block] = []
    for page in pages:
        blocks.append(PageBreak(label=source.page_labels[page.page - 1], page=page.page))
        blocks.extend(Paragraph([Text(text)]) for text in page.blocks)
    chapter = Chapter(title=metadata.title, blocks=blocks)
    document = Document(
        metadata=metadata, chapters=[chapter], toc=[TocEntry(metadata.title, chapter=0)]
    )
    return document, issues


def _metadata(source: SourcePdf, options: ConversionOptions) -> tuple[Metadata, list[Issue]]:
    issues: list[Issue] = []
    info = {key: normalise(value).strip() for key, value in source.info.items()}
    title = options.title or info.get("Title") or source.path.stem
    if options.authors is not None:
        authors = list(options.authors)
    else:
        authors = [info["Author"]] if info.get("Author") else []
    language = options.language or source.language
    if not language:
        language = DEFAULT_LANGUAGE
        issues.append(
            Issue(
                IssueCode.LANGUAGE_DEFAULTED,
                f"No language was given or found; the book was labelled {DEFAULT_LANGUAGE}.",
            )
        )
    identifier = uuid.uuid5(IDENTIFIER_NAMESPACE, source.sha256)
    modified = (
        _pdf_date(info.get("ModDate")) or _pdf_date(info.get("CreationDate")) or DEFAULT_MODIFIED
    )
    metadata = Metadata(
        title=title,
        authors=authors,
        language=language,
        identifier=f"urn:uuid:{identifier}",
        modified=modified,
    )
    return metadata, issues


def _pdf_date(value: str | None) -> str | None:
    """A PDF date string (``D:YYYYMMDDHHmmSSOHH'mm'``) as ``CCYY-MM-DDThh:mm:ssZ`` in UTC
    (EPUB-R14), or None if it isn't one."""
    match = _PDF_DATE.match(value or "")
    if match is None:
        return None
    year, month, day, hour, minute, second, zulu, sign, tz_hour, tz_minute = match.groups()
    offset = timedelta(hours=int(tz_hour or 0), minutes=int(tz_minute or 0))
    zone = timezone(-offset if sign == "-" else offset) if sign and not zulu else UTC
    try:
        moment = datetime(
            int(year),
            int(month or 1),
            int(day or 1),
            int(hour or 0),
            int(minute or 0),
            int(second or 0),
            tzinfo=zone,
        )
    except ValueError:
        return None
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
