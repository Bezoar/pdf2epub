"""Joining a paragraph's lines into text: de-hyphenation (RFL-R17) and line joins
(RFL-R19), including the page-break markers of a paragraph joined across pages
(RFL-R18)."""

import re
from collections.abc import Collection
from dataclasses import dataclass

from pdf2epub.reflow.extract import Line
from pdf2epub.reflow.model import Inline, PageBreak, Text

# A line that ends in a hyphen after a letter or digit breaks a word.
_HYPHEN_END = re.compile(r"(?<=\w)[-\u2010]$")
_LAST_WORD = re.compile(r"([^\W\d_]+)[-\u2010]$")
_FIRST_WORD = re.compile(r"^[^\W\d_]+")
_TERMINAL = re.compile(r"[.!?\u2026][\"'\u201d\u2019)\]\u00bb]*$")
_CJK = re.compile(
    "[\u2e80-\u2fdf\u3000-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\uff00-\uffef]"
)


@dataclass(frozen=True)
class Join:
    """A join point inside a paragraph: the page break before the next line's text."""

    marker: PageBreak


def ends_sentence(text: str) -> bool:
    """``text`` ends with terminal punctuation (allowing closing quotes or brackets)."""
    return _TERMINAL.search(text) is not None


def paragraph_inlines(items: list[Line | Join], words: Collection[str] | None) -> list[Inline]:
    """The inlines of a paragraph made of these lines, with a ``PageBreak`` inline at each
    join point between pages. ``words`` is the language's wordlist, or None."""
    text = ""
    soft = False
    breaks: list[tuple[int, PageBreak]] = []
    pending: list[PageBreak] = []
    for item in items:
        if isinstance(item, Join):
            pending.append(item.marker)
            continue
        if not text:
            breaks.extend((0, marker) for marker in pending)
        else:
            text, glued = _join(text, soft, item.text, words)
            # A marker sits at the join, or after the word the join completed.
            word = item.text.split(" ", 1)[0]
            at = len(text) - len(item.text) + (len(word) if glued else 0)
            breaks.extend((at, marker) for marker in pending)
        if not text:
            text = item.text
        pending = []
        soft = item.soft_hyphen
    breaks.extend((len(text), marker) for marker in pending)
    return _split(text, breaks)


def _join(text: str, soft: bool, line: str, words: Collection[str] | None) -> tuple[str, bool]:
    """Append ``line`` to ``text``; also say whether they were glued without a space."""
    if soft:
        return text + line, True
    if _HYPHEN_END.search(text):
        head, tail = _LAST_WORD.search(text), _FIRST_WORD.match(line)
        if head and tail and words is not None and _known(head.group(1) + tail.group(0), words):
            return text[:-1] + line, True
        return text + line, True
    if _CJK.match(text[-1]) and _CJK.match(line[0]):
        return text + line, False
    return f"{text} {line}", False


def _known(word: str, words: Collection[str]) -> bool:
    return word in words or word.lower() in words


def _split(text: str, breaks: list[tuple[int, PageBreak]]) -> list[Inline]:
    inlines: list[Inline] = []
    start = 0
    for at, marker in breaks:
        if at > start:
            inlines.append(Text(text[start:at]))
        inlines.append(marker)
        start = max(start, at)
    if start < len(text) or not inlines:
        inlines.append(Text(text[start:]))
    return inlines
