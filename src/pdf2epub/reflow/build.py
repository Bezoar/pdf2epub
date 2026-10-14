"""Building the document model from a source PDF and its page text (RFL-R25, RFL-R31,
RFL-R32, RFL-R34).

Every page's lines are grouped into blocks and paragraphs (``reflow.layout``), furniture
is removed (``reflow.furniture``, RFL-R16), and a paragraph left open at the end of a page
is joined to the first paragraph of the next (RFL-R18), with its lines de-hyphenated and
joined (``reflow.text``, RFL-R17, RFL-R19). Line blocks (verse, code) keep their lines
and are never joined (``reflow.lineblocks``, RFL-R36). Each page starts with a page-break marker: a
block, or an inline where a paragraph runs on across the page boundary.

The book is still one chapter; headings, chapters from the outline, images and the cover
come with later tickets.
"""

import re
import uuid
from collections.abc import Collection
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta, timezone

from pdf2epub.issues import Issue, IssueCode
from pdf2epub.options import ConversionOptions
from pdf2epub.reflow.extract import Line, PageText, normalise
from pdf2epub.reflow.furniture import Furniture, PageBlocks, find_furniture
from pdf2epub.reflow.layout import DraftParagraph, group_blocks, measure, paragraphs
from pdf2epub.reflow.lineblocks import is_line_block, line_block
from pdf2epub.reflow.model import (
    Block,
    Chapter,
    Document,
    LineBlock,
    Metadata,
    PageBreak,
    Paragraph,
    TocEntry,
)
from pdf2epub.reflow.sequence import sequence_gaps
from pdf2epub.reflow.source import SourcePdf
from pdf2epub.reflow.text import Join, ends_sentence, paragraph_inlines
from pdf2epub.reflow.wordlists import wordlist

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
    blocks, furniture = _body(source, pages, wordlist(metadata.language))
    gaps = sequence_gaps(furniture.page_numbers)
    if gaps is not None:
        issues.append(gaps)
    chapter = Chapter(title=metadata.title, blocks=blocks)
    document = Document(
        metadata=metadata, chapters=[chapter], toc=[TocEntry(metadata.title, chapter=0)]
    )
    return document, issues


@dataclass
class _Open:
    """A paragraph being assembled, possibly across pages."""

    last: DraftParagraph
    """The part on the latest page."""
    items: list[Line | Join] = field(default_factory=list)


def _body(
    source: SourcePdf, pages: list[PageText], words: Collection[str] | None
) -> tuple[list[Block], Furniture]:
    typography = measure(pages)
    laid_out = [PageBlocks(p.page, p.height, group_blocks(p.lines, typography)) for p in pages]
    furniture = find_furniture(laid_out, typography)
    stream: list[PageBreak | LineBlock | _Open] = []
    for page in laid_out:
        marker = PageBreak(label=source.page_labels[page.page - 1], page=page.page)
        drafts: list[DraftParagraph | LineBlock] = []
        for index, block in enumerate(page.blocks):
            if (page.page, index) in furniture.removed:
                continue
            if is_line_block(block, typography):
                drafts.append(line_block(block))  # RFL-R36: kept line by line
            else:
                drafts.extend(paragraphs(block, typography))
        last = stream[-1] if stream else None
        first = drafts[0] if drafts else None
        if (
            isinstance(first, DraftParagraph)
            and isinstance(last, _Open)
            and _runs_on(last.last, first)
        ):
            last.items.append(Join(marker))
            last.items.extend(first.lines)
            last.last = first
            drafts.pop(0)
        else:
            stream.append(marker)
        stream.extend(
            _Open(draft, list(draft.lines)) if isinstance(draft, DraftParagraph) else draft
            for draft in drafts
        )
    blocks: list[Block] = [
        Paragraph(paragraph_inlines(item.items, words)) if isinstance(item, _Open) else item
        for item in stream
    ]
    return blocks, furniture


def _runs_on(end: DraftParagraph, start: DraftParagraph) -> bool:
    """A paragraph ending a page runs on into the first paragraph of the next (RFL-R18)."""
    if end.display or start.display or ends_sentence(end.lines[-1].text):
        return False
    return start.lines[0].text[:1].islower() or not start.indented


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
