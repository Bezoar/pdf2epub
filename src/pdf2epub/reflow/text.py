"""Joining a paragraph's lines into text: de-hyphenation (RFL-R17) and line joins
(RFL-R19), including the page-break markers of a paragraph joined across pages
(RFL-R18), and keeping the lines' bold and italic runs (RFL-R22)."""

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
    styles: list[_Style] = []
    soft = False
    breaks: list[tuple[int, PageBreak]] = []
    pending: list[PageBreak] = []
    for item in items:
        if isinstance(item, Join):
            pending.append(item.marker)
            continue
        line_styles = [(run.bold, run.italic) for run in item.styled for _ in run.text]
        if not text:
            breaks.extend((0, marker) for marker in pending)
            text, styles = item.text, line_styles
        else:
            joined = _join(text, soft, item.text, words)
            # A marker sits right before the text of the page it starts.
            at = len(joined) - len(item.text)
            kept = styles[:at]
            if at > len(styles):  # a space was added between the lines
                kept.append(_space(styles[-1], line_styles[0]))
            text, styles = joined, kept + line_styles
            breaks.extend((at, marker) for marker in pending)
        pending = []
        soft = item.soft_hyphen
    breaks.extend((len(text), marker) for marker in pending)
    return _split(text, styles, breaks)


_Style = tuple[bool, bool]


def _space(before: _Style, after: _Style) -> _Style:
    return before[0] and after[0], before[1] and after[1]


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


def _split(text: str, styles: list[_Style], breaks: list[tuple[int, PageBreak]]) -> list[Inline]:
    inlines: list[Inline] = []
    cuts = sorted({0, len(text), *(at for at, _ in breaks)} | _style_changes(styles))
    markers = iter(sorted(breaks, key=lambda item: item[0]))
    marker = next(markers, None)
    for start, end in zip(cuts, [*cuts[1:], None], strict=True):
        while marker is not None and marker[0] == start:
            inlines.append(marker[1])
            marker = next(markers, None)
        if end is not None and end > start:
            bold, italic = styles[start] if start < len(styles) else (False, False)
            inlines.append(Text(text[start:end], bold, italic))
    if not inlines:
        inlines.append(Text(text))
    return inlines


def _style_changes(styles: list[_Style]) -> set[int]:
    return {i for i in range(1, len(styles)) if styles[i] != styles[i - 1]}
