"""The book's metadata (RFL-R31, RFL-R32, EPUB-R13, EPUB-R14).

Title and authors come from the first source that supplies them: the options, the XMP
packet, the Info dictionary, the ``Author - Title.pdf`` file name pattern, and (title
only) the file name's stem. The language comes from the options, the catalog ``/Lang``
or XMP ``dc:language``, else ``en`` with a ``language_defaulted`` warning. The identifier
and the modification date are derived from the file alone, so output is deterministic.
"""

import logging
import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta, timezone

from lxml import etree

from pdf2epub.issues import Issue, IssueCode
from pdf2epub.options import ConversionOptions
from pdf2epub.reflow.extract import normalise
from pdf2epub.reflow.model import Metadata
from pdf2epub.reflow.source import SourcePdf

log = logging.getLogger(__name__)

# Fixed once for pdf2epub: dc:identifier is urn:uuid: plus UUIDv5(this, the PDF's SHA-256).
IDENTIFIER_NAMESPACE = uuid.UUID("de933f19-549d-40b3-bd7c-840b7f360868")
DEFAULT_LANGUAGE = "en"
DEFAULT_MODIFIED = "1980-01-01T00:00:00Z"

_PDF_DATE = re.compile(
    r"^(?:D:)?(\d{4})(\d{2})?(\d{2})?(\d{2})?(\d{2})?(\d{2})?"
    r"(?:([Zz])|([+-])(\d{2})'?(\d{2})?'?)?"
)
# RFL-R31: "Author - Title"; authors are split on " & " and ", ".
_FILE_NAME = re.compile(r"^(?P<authors>.+?) - (?P<title>.+)$")
_AUTHOR_SEPARATORS = re.compile(r" & |, ")

_DC = "http://purl.org/dc/elements/1.1/"
_RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
_XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"
# The XMP packet is untrusted XML: no DTDs, no entities, no network, no huge trees.
_XMP_PARSER = etree.XMLParser(
    resolve_entities=False, no_network=True, load_dtd=False, huge_tree=False, remove_pis=True
)


@dataclass(frozen=True)
class Xmp:
    """What the book takes from an XMP packet."""

    title: str | None = None
    authors: list[str] = field(default_factory=list)
    language: str | None = None


def read_xmp(packet: bytes | None) -> Xmp:
    """The Dublin Core title, creators and language of an XMP ``packet``. A packet that
    is missing or isn't well-formed XML supplies nothing."""
    if not packet:
        return Xmp()
    try:
        root = etree.fromstring(packet.strip(), _XMP_PARSER)
    except etree.XMLSyntaxError:
        log.debug("the XMP metadata is not well-formed; it is ignored", exc_info=True)
        return Xmp()
    if root is None:
        return Xmp()
    titles = _values(root, "title")
    languages = _values(root, "language")
    return Xmp(
        title=titles[0] if titles else None,
        authors=_values(root, "creator"),
        language=languages[0] if languages else None,
    )


def _values(root: etree._Element, name: str) -> list[str]:
    """The non-empty values of the first ``dc:name`` property: its ``rdf:li`` items in
    order (the ``x-default`` one first, in an ``rdf:Alt``), or its text."""
    element = next(root.iter(f"{{{_DC}}}{name}"), None)
    if element is None:
        return []
    items = list(element.iter(f"{{{_RDF}}}li"))
    if not items:
        items = [element]
    if element.find(f"{{{_RDF}}}Alt") is not None:
        # A language alternative (a title): the x-default item first. Sequences and bags
        # (creators, languages) keep their order.
        items.sort(key=lambda item: item.get(_XML_LANG) != "x-default")
    values = (
        " ".join(normalise("".join(str(text) for text in item.itertext())).split())
        for item in items
    )
    return [value for value in values if value]


def book_metadata(source: SourcePdf, options: ConversionOptions) -> tuple[Metadata, list[Issue]]:
    """The metadata for ``source``, and the issues found deciding it."""
    issues: list[Issue] = []
    xmp = read_xmp(source.xmp)
    info = {key: normalise(value).strip() for key, value in source.info.items()}
    named = _FILE_NAME.match(source.path.stem)
    from_name = [a for a in _AUTHOR_SEPARATORS.split(named["authors"]) if a] if named else []

    title = (
        options.title
        or xmp.title
        or info.get("Title")
        or (named["title"] if named else None)
        or source.path.stem
    )
    if options.authors is not None:
        authors = list(options.authors)
    elif xmp.authors:
        authors = xmp.authors
    elif info.get("Author"):
        authors = [info["Author"]]
    else:
        authors = from_name

    language = options.language or source.language or xmp.language
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
    try:
        offset = timedelta(hours=int(tz_hour or 0), minutes=int(tz_minute or 0))
        zone = timezone(-offset if sign == "-" else offset) if sign and not zulu else UTC
        moment = datetime(
            int(year),
            int(month or 1),
            int(day or 1),
            int(hour or 0),
            int(minute or 0),
            int(second or 0),
            tzinfo=zone,
        ).astimezone(UTC)
    except (ValueError, OverflowError):
        return None
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")
