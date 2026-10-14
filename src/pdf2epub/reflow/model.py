"""The document model (RFL-R34): reflow's output and the EPUB writer's only input.

It holds no PDF objects. Book images and the cover join the model with the tickets that
produce them. ``page`` is always the 1-based PDF page index (unique within a
book); ``label`` is the printed page label, for display only.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Text:
    """A run of text with its inline marks."""

    text: str
    bold: bool = False
    italic: bool = False


@dataclass(frozen=True)
class PageBreak:
    """The start of a PDF page: a block between blocks, or an inline inside a paragraph
    joined across pages."""

    label: str
    page: int


Inline = Text | PageBreak


@dataclass(frozen=True)
class Heading:
    level: int
    inlines: list[Inline]
    anchor: str


@dataclass(frozen=True)
class Paragraph:
    inlines: list[Inline]


@dataclass(frozen=True)
class LineBlock:
    """A line block (RFL-R36): verse, code or other text whose line breaks carry meaning.
    Its lines are kept as in the source, never joined or de-hyphenated."""

    lines: list[list[Inline]]
    monospace: bool = False
    """Set wholly in a monospace font; its lines keep their spaces, leading ones too."""


@dataclass(frozen=True)
class ImageAsset:
    """An image stored once in the book (RFL-R26), whatever refers to it."""

    name: str
    """Its file name in the book, e.g. ``page-3.png``: unique within the book."""
    media_type: str
    data: bytes


@dataclass(frozen=True)
class PageImage:
    """A page-image fallback (RFL-R15): a render of the whole page, with the page's text
    kept searchable."""

    asset: str
    """The ``name`` of its ``ImageAsset`` in ``Document.images``."""
    text: str | None
    """Its searchable text, one line per line of the page (in column order on a
    multi-column page); None when the page has none."""
    page: int


Block = Heading | Paragraph | LineBlock | PageImage | PageBreak


@dataclass(frozen=True)
class Chapter:
    title: str | None
    """None for front matter."""
    blocks: list[Block]


@dataclass(frozen=True)
class TocEntry:
    label: str
    chapter: int
    """Index into ``Document.chapters``."""
    anchor: str | None = None
    """An anchor inside the chapter, or None for its start."""
    children: list["TocEntry"] = field(default_factory=list)


@dataclass(frozen=True)
class Metadata:
    title: str
    authors: list[str]
    language: str
    identifier: str
    """The book's unique identifier, e.g. ``urn:uuid:...`` (EPUB-R13)."""
    modified: str
    """``CCYY-MM-DDThh:mm:ssZ`` (EPUB-R14)."""


@dataclass(frozen=True)
class Document:
    metadata: Metadata
    chapters: list[Chapter]
    toc: list[TocEntry]
    images: list[ImageAsset] = field(default_factory=list)
    """Every image the blocks refer to, each stored once."""
