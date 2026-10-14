"""Building the document model from a source PDF and its page text (RFL-R25, RFL-R31,
RFL-R32, RFL-R34).

Every page's lines are grouped into blocks and paragraphs (``reflow.layout``), furniture
is removed (``reflow.furniture``, RFL-R16), headings are found (``reflow.headings``,
RFL-R20) and images are placed with their captions (RFL-R26). A paragraph left open at
the end of a page is joined to the first paragraph of the next (RFL-R18), skipping over
images between them, with its lines de-hyphenated and joined (``reflow.text``, RFL-R17,
RFL-R19). Line blocks (verse, code) keep their lines and are never joined
(``reflow.lineblocks``, RFL-R36). Each page starts with a page-break marker: a block, or
an inline where a paragraph runs on across the page boundary. The blocks are then split
into chapters with a table of contents (``reflow.chapters``, RFL-R23, RFL-R24).

Page images and the cover come with later tickets.
"""

import re
import uuid
from collections.abc import Collection
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta, timezone
from itertools import pairwise

from pdf2epub.issues import Issue, IssueCode
from pdf2epub.options import ConversionOptions
from pdf2epub.reflow.chapters import Position, make_chapters
from pdf2epub.reflow.extract import Line, PageText, normalise
from pdf2epub.reflow.furniture import Furniture, PageBlocks, find_furniture
from pdf2epub.reflow.headings import heading_levels
from pdf2epub.reflow.images import PlacedImage
from pdf2epub.reflow.layout import (
    DraftParagraph,
    TextBlock,
    Typography,
    group_blocks,
    measure,
    paragraphs,
)
from pdf2epub.reflow.lineblocks import is_line_block, line_block
from pdf2epub.reflow.model import (
    Block,
    Document,
    Heading,
    Image,
    ImageAsset,
    LineBlock,
    Metadata,
    PageBreak,
    Paragraph,
    Text,
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
    source: SourcePdf,
    pages: list[PageText],
    images: dict[int, list[PlacedImage]],
    options: ConversionOptions,
) -> tuple[Document, list[Issue]]:
    """The document model for ``source`` from its pages' text and images, and the issues
    found while building it."""
    metadata, issues = _metadata(source, options)
    blocks, positions, furniture = _body(source, pages, images, wordlist(metadata.language))
    gaps = sequence_gaps(furniture.page_numbers)
    if gaps is not None:
        issues.append(gaps)
    outline = [replace(entry, title=normalise(entry.title).strip()) for entry in source.outline]
    chapters, toc = make_chapters(blocks, positions, outline, metadata.title)
    assets: dict[ImageAsset, None] = {}
    for block in blocks:
        if isinstance(block, Image):
            assets.setdefault(block.asset)
    document = Document(metadata=metadata, chapters=chapters, toc=toc, images=list(assets))
    return document, issues


# A caption sits within this many body sizes of its image, above or below it.
_CAPTION_GAP_EM = 2.0
# A caption is at most this many lines, set at least this much smaller than body text.
_CAPTION_LINES, _CAPTION_SMALLER = 3, 0.5


@dataclass
class _Open:
    """A paragraph being assembled, possibly across pages."""

    last: DraftParagraph
    """The part on the latest page."""
    items: list[Line | Join] = field(default_factory=list)


@dataclass(frozen=True)
class _Heading:
    lines: list[Line]
    level: int


_Item = PageBreak | _Open | _Heading | LineBlock | Image


def _body(
    source: SourcePdf,
    pages: list[PageText],
    images: dict[int, list[PlacedImage]],
    words: Collection[str] | None,
) -> tuple[list[Block], list[Position], Furniture]:
    """The book's blocks in reading order, with where each starts, and its furniture."""
    typography = measure(pages)
    laid_out = [PageBlocks(p.page, p.height, group_blocks(p.lines, typography)) for p in pages]
    furniture = find_furniture(laid_out, typography)
    levels = heading_levels(laid_out, furniture.removed, typography)
    stream: list[tuple[_Item, Position]] = []
    open_paragraph: _Open | None = None
    for page in laid_out:
        marker = PageBreak(label=source.page_labels[page.page - 1], page=page.page)
        kept = [
            (index, block)
            for index, block in enumerate(page.blocks)
            if (page.page, index) not in furniture.removed
        ]
        text_blocks = [(i, b) for i, b in kept if (page.page, i) not in levels]
        placed, captions = _place_images(images.get(page.page, []), text_blocks, typography, words)
        found: list[tuple[float, _Item]] = [(image_top, image) for image_top, image in placed]
        for index, block in kept:
            if index in captions:
                continue
            level = levels.get((page.page, index))
            if level is not None:
                found.append((block.top, _Heading(block.lines, level)))
            elif is_line_block(block, typography):
                found.append((block.top, line_block(block)))  # RFL-R36: kept line by line
            else:
                found.extend(
                    (part.lines[0].top, _Open(part, list(part.lines)))
                    for draft in paragraphs(block, typography)
                    for part in _split_at_images(draft, images.get(page.page, []))
                )
        found.sort(key=lambda entry: entry[0])
        first_text = next(
            (n for n, (_, item) in enumerate(found) if not isinstance(item, Image)), None
        )
        if (
            open_paragraph is not None
            and first_text is not None
            and isinstance(start := found[first_text][1], _Open)
            and _runs_on(open_paragraph.last, start.last)
        ):
            open_paragraph.items.append(Join(marker))
            open_paragraph.items.extend(start.items)
            open_paragraph.last = start.last
            del found[first_text]
        elif open_paragraph is not None and found and first_text is None:
            # A page of images only: the paragraph may still run on past them (RFL-R18),
            # so this page's marker goes inside it and the images after it.
            open_paragraph.items.append(Join(marker))
        else:
            stream.append((marker, (page.page, -1.0)))
            open_paragraph = None
        for top, item in found:
            stream.append((item, (page.page, top)))
            if not isinstance(item, Image):
                open_paragraph = item if isinstance(item, _Open) else None
    blocks: list[Block] = []
    headings = 0
    for item, _ in stream:
        if isinstance(item, _Open):
            blocks.append(Paragraph(paragraph_inlines(item.items, words)))
        elif isinstance(item, _Heading):
            headings += 1
            inlines = paragraph_inlines(list(item.lines), words)
            blocks.append(Heading(item.level, inlines, anchor=f"heading-{headings}"))
        else:
            blocks.append(item)
    return blocks, [position for _, position in stream], furniture


# Points of slack when deciding that an image sits in the gap between two lines.
_GAP_SLACK = 1.0


def _split_at_images(draft: DraftParagraph, images: list[PlacedImage]) -> list[DraftParagraph]:
    """Split a paragraph's lines where an image sits in the gap between two of them, so
    the image keeps its place in reading order."""
    parts = [[draft.lines[0]]]
    for above, below in pairwise(draft.lines):
        if any(
            image.top >= above.bottom - _GAP_SLACK
            and image.bottom <= below.top + _GAP_SLACK
            and any(min(image.x1, line.x1) > max(image.x0, line.x0) for line in (above, below))
            for image in images
        ):
            parts.append([])
        parts[-1].append(below)
    return [
        replace(draft, lines=lines, indented=draft.indented and n == 0)
        for n, lines in enumerate(parts)
    ]


def _place_images(
    images: list[PlacedImage],
    blocks: list[tuple[int, TextBlock]],
    typography: Typography,
    words: Collection[str] | None,
) -> tuple[list[tuple[float, Image]], set[int]]:
    """Each image as an ``Image`` block at its top, with its caption: the adjacent short
    block in smaller type directly below it or, failing that, above it (RFL-R12). Returns
    the images and the indices of the blocks taken as captions."""
    taken: set[int] = set()
    placed: list[tuple[float, Image]] = []
    reach = _CAPTION_GAP_EM * typography.body_size
    for image in images:
        candidates = [
            (index, block)
            for index, block in blocks
            if index not in taken
            and len(block.lines) <= _CAPTION_LINES
            and block.size <= typography.body_size - _CAPTION_SMALLER
            and min(block.lines[0].x1, image.x1) > max(block.lines[0].x0, image.x0)
        ]
        below = [(i, b) for i, b in candidates if 0 <= b.top - image.bottom + 1 <= reach]
        above = [(i, b) for i, b in candidates if 0 <= image.top - b.bottom + 1 <= reach]
        caption = None
        for index, block in below[:1] or above[-1:]:
            taken.add(index)
            inlines = paragraph_inlines(list(block.lines), words)
            caption = "".join(i.text for i in inlines if isinstance(i, Text))
        placed.append((image.top, Image(image.asset, caption)))
    return placed, taken


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
