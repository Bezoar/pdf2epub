"""Pages that the two parsers don't both read (RFL-R37).

pdfium counts the pages and renders them; pdfminer.six reads their text. A page is
unreadable when pdfium counts it but can't load it, when pdfminer.six can't parse it, or
when, even after repair, the two read different numbers of pages and only one of them
has it (pages are matched by position: neither parser says which of its pages is which
of the other's). Each keeps its place in the book with a visible notice: a page pdfium
renders (one only pdfium has, or one pdfminer.six can't parse) becomes a page image,
with the text pdfium reads on it kept searchable; any other unreadable page keeps the
text pdfminer.six recovered from it, if any.
"""

from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass, replace

from pdf2epub.passwords import Secret
from pdf2epub.reflow.extract import PageText, normalise
from pdf2epub.reflow.source import SourcePdf, page_text


@dataclass(frozen=True)
class UnreadablePage:
    page: int
    """1-based page index."""
    rendered: bool
    """pdfium renders it: it becomes a page image."""
    text: str | None
    """What was recovered of its text, one line per line, or None: pdfium's for a
    rendered page, pdfminer.six's otherwise."""


def unreadable_page_numbers(source: SourcePdf, found: int) -> frozenset[int]:
    """The unreadable pages of ``source`` known before pdfminer.six parses any page, where
    it found ``found`` pages."""
    shared = min(source.page_count, found)
    beyond = range(shared + 1, max(source.page_count, found) + 1)
    return source.unloadable | frozenset(beyond)


def unreadable_pages(
    source: SourcePdf,
    found: int,
    recovered: Mapping[int, PageText],
    password: Secret | None = None,
    unparseable: Collection[int] = frozenset(),
) -> dict[int, UnreadablePage]:
    """Each unreadable page of ``source`` (opened with ``password`` if it needs one), by
    page index, where pdfminer.six found ``found`` pages, read ``recovered`` among the
    unreadable ones and couldn't parse ``unparseable``."""
    numbers = unreadable_page_numbers(source, found) | frozenset(unparseable)
    rendered = {n for n in numbers if n <= source.page_count and n not in source.unloadable}
    texts = page_text(source.path, rendered, password)
    pages: dict[int, UnreadablePage] = {}
    for number in sorted(numbers):
        if number in rendered:
            text = _lines(texts[number].splitlines())
        elif number in recovered:
            text = _lines(line.text for line in recovered[number].lines)
        else:
            text = None
        pages[number] = UnreadablePage(number, number in rendered, text)
    return pages


def with_page_count(source: SourcePdf, count: int) -> SourcePdf:
    """``source`` with ``count`` pages: the pages beyond pdfium's count, which only
    pdfminer.six has, get their 1-based index as their label (RFL-R25)."""
    extra = [str(number) for number in range(source.page_count + 1, count + 1)]
    return replace(source, page_labels=[*source.page_labels, *extra])


def _lines(lines: Iterable[str]) -> str | None:
    kept = [text for line in lines if (text := " ".join(normalise(line).split()))]
    return "\n".join(kept) or None
