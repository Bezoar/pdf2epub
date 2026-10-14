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
# Chinese and Japanese, whose lines join with no space: Han ideographs (including the
# supplementary planes' extensions and compatibility ideographs), Hiragana and Katakana
# (with the supplementary kana blocks), and CJK, vertical and full-width punctuation.
# Korean (Hangul) separates words with spaces, so it is not here: its lines join with a
# space, like Latin text.
_NO_SPACE = re.compile(
    "[\u2e80-\u2fdf\u3000-\u30ff\u31f0-\u31ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff"
    "\ufe10-\ufe1f\ufe30-\ufe4f\uff00-\uff9f\uffe0-\uffef"
    "\U0001aff0-\U0001b16f\U00020000-\U0003134f]"
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
            text = _join(text, soft, item.text, words)
            # A marker sits right before the text of the page it starts.
            at = len(text) - len(item.text)
            breaks.extend((at, marker) for marker in pending)
        if not text:
            text = item.text
        pending = []
        soft = item.soft_hyphen
    breaks.extend((len(text), marker) for marker in pending)
    return _split(text, breaks)


def _join(text: str, soft: bool, line: str, words: Collection[str] | None) -> str:
    """Append ``line`` to ``text``, de-hyphenating a word broken at the line end."""
    if soft:
        return text + line
    if _HYPHEN_END.search(text):
        head, tail = _LAST_WORD.search(text), _FIRST_WORD.match(line)
        if head and tail and words is not None and _known(head.group(1) + tail.group(0), words):
            return text[:-1] + line
        return text + line
    if _NO_SPACE.match(text[-1]) and _NO_SPACE.match(line[0]):
        return text + line
    return f"{text} {line}"


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
