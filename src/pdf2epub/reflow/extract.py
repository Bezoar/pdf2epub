"""Per-page text extraction with pdfminer.six (RFL-R1, RFL-R7) and text normalisation
(RFL-R8).

Each page comes out as its text lines in reading order (top to bottom), with their
geometry and font size: layout analysis (``reflow.layout``) groups them into blocks and
paragraphs. A line's text is normalised; a soft hyphen at its end is removed from the
text but kept as a flag, so de-hyphenation still sees the word break (RFL-R17). A line
also keeps its runs of bold and italic text (RFL-R22).

A page set in more than one column (``reflow.columns``, RFL-R11) comes out in column
order instead: every line of one column, top to bottom, before any line of the next,
with lines across the columns (a heading, a page number) between the parts they divide
(RFL-R15). Lines are split at a gutter even where pdfminer ran them together. Each page
also carries what its complexity is measured from (``reflow.complexity``, RFL-R13).
"""

import math
import re
import unicodedata
from collections import Counter
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass, field
from itertools import pairwise

import numpy as np
from pdfminer.layout import (
    LAParams,
    LTAnno,
    LTChar,
    LTComponent,
    LTContainer,
    LTCurve,
    LTFigure,
    LTImage,
    LTItem,
    LTLine,
    LTPage,
    LTRect,
    LTTextContainer,
    LTTextLine,
)

from pdf2epub.reflow.columns import Gutter, Piece, column_of, find_gutters, split
from pdf2epub.reflow.model import Text
from pdf2epub.reflow.parse import STYLE, ParsedPdf

# Characters XML 1.0 does not allow, which a text layer can still carry.
_NOT_XML = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\ufffe\uffff\ud800-\udfff]")
SOFT_HYPHEN = "\u00ad"
LIGATURES = str.maketrans(
    {
        "\ufb00": "ff",
        "\ufb01": "fi",
        "\ufb02": "fl",
        "\ufb03": "ffi",
        "\ufb04": "ffl",
        "\ufb05": "st",
        "\ufb06": "st",
    }
)
# Two text lines are one row when they overlap vertically by more than this share of the
# shorter one (pdfminer can split a line at a wide horizontal gap).
_SAME_ROW = 0.5
# Pieces of one row this many ems apart or closer are one line of text.
_PIECE_GAP_EM = 3.0
# Font names of common monospace faces (RFL-R36).
_MONO_NAME = re.compile(r"courier|mono|consol|menlo|typewriter|fixed", re.IGNORECASE)
# Glyph advances within this share of each other are the same advance.
MONO_SPREAD = 0.01
# Fonts that set mathematics (TeX's math fonts, Symbol, STIX, Cambria Math and the like).
_MATH_FONT = re.compile(r"cmmi|cmsy|cmex|msam|msbm|symbol|math|stix|euler", re.IGNORECASE)
# A drawn line or a rectangle this thin, in points, is a rule.
_RULE_THICKNESS = 2.0
# An image covering this share of the page is a scan, not an illustration on the page.
_SCAN_SHARE = 0.9
# The resolution, in points, of the mask that measures the area under shapes, made
# coarser for a page so large (a hostile one can be) that the mask would pass this
# many cells along an edge.
_MASK_STEP, _MAX_MASK_EDGE = 2.0, 2_000


@dataclass(frozen=True)
class Line:
    """One line of text on a page, in page coordinates measured from the top-left."""

    text: str
    """Normalised, with runs of whitespace collapsed to one space."""
    x0: float
    x1: float
    top: float
    bottom: float
    size: float
    """The line's most common character size, in points."""
    soft_hyphen: bool = False
    """The line ended in a soft hyphen (removed from ``text``)."""
    monospace: bool = False
    """Every glyph of the line is set in a font named as monospace (RFL-R36)."""
    advance: float = 0.0
    """The glyph advance, in points, when every glyph of the line has the same one (as in
    a monospace font, whatever its name); 0 otherwise."""
    verbatim: str = ""
    """When ``advance`` is set: the normalised text with its spaces kept, leading ones
    included (only trailing whitespace removed); empty otherwise."""
    runs: tuple[Text, ...] = ()
    """``text`` as runs of bold and italic; empty when it is all plain."""

    @property
    def styled(self) -> tuple[Text, ...]:
        """``text`` as runs, never empty."""
        return self.runs or (Text(self.text),)

    @property
    def bold(self) -> bool:
        """Every letter of the line is bold."""
        return all(run.bold for run in self.styled if run.text.strip())


@dataclass(frozen=True)
class Rule:
    """A ruled line: a drawn line or a thin rectangle, in page coordinates measured from
    the top-left."""

    x0: float
    x1: float
    top: float
    bottom: float

    @property
    def horizontal(self) -> bool:
        return self.x1 - self.x0 >= self.bottom - self.top


@dataclass(frozen=True)
class Graphics:
    """What a page's complexity is measured from (RFL-R13), besides its lines."""

    rules: list[Rule] = field(default_factory=list)
    """Ruled lines at least an em long."""
    covered: float = 0.0
    """The share of the page area under images and filled vector shapes (rules and
    full-page scans aside)."""
    glyphs: int = 0
    """Glyphs other than spaces, outside monospace lines (code)."""
    math: int = 0
    """Of those, the mathematical ones: math symbols, mathematical letters, or any glyph
    set in a math font."""


@dataclass(frozen=True)
class PageText:
    """The text lines of one page, in reading order."""

    page: int
    """1-based PDF page index."""
    width: float
    height: float
    lines: list[Line]
    """Top to bottom; in column order when ``columns`` is more than 1."""
    columns: int = 1
    """How many text columns the page is set in (RFL-R11)."""
    graphics: Graphics = field(default_factory=Graphics)


def normalise(text: str) -> str:
    """Unicode NFC, with ligatures expanded, soft hyphens removed and characters that XML
    can't carry dropped (RFL-R8)."""
    text = text.translate(LIGATURES).replace(SOFT_HYPHEN, "")
    return _NOT_XML.sub("", unicodedata.normalize("NFC", text))


def read_pages(pdf: ParsedPdf) -> Iterator[PageText]:
    """Yield each page's text lines, one page at a time."""
    for number, layout in enumerate(pdf.layouts(LAParams()), start=1):
        items = [
            item
            for element in layout
            if isinstance(element, LTTextContainer)
            for item in element
            if isinstance(item, LTTextLine)
        ]
        pieces = [_piece(list(item), layout.height) for item in items]
        gutters = find_gutters(pieces)
        if gutters:
            lines = _in_columns(items, pieces, gutters, layout.height)
        else:
            lines = _rows([line for item in items if (line := _line(list(item), layout.height))])
        yield PageText(
            number,
            layout.width,
            layout.height,
            lines,
            columns=len(gutters) + 1,
            graphics=_graphics(layout, lines),
        )


def _piece(children: Sequence[LTItem], page_height: float) -> Piece:
    chars = [c for c in children if isinstance(c, LTChar)]
    if not chars:
        return Piece([], 0.0, 0.0, 0.0)
    return Piece(
        [(c.x0, c.x1) for c in chars],
        page_height - max(c.y1 for c in chars),
        page_height - min(c.y0 for c in chars),
        Counter(round(c.size, 1) for c in chars).most_common(1)[0][0],
    )


def _in_columns(
    items: list[LTTextLine], pieces: list[Piece], gutters: list[Gutter], page_height: float
) -> list[Line]:
    """The page's lines in column order (RFL-R15): each part of the page between lines
    that cross the columns is read column by column, left to right."""
    placed: list[tuple[Line, int | None]] = []
    for item, piece in zip(items, pieces, strict=True):
        children = list(item)
        groups = split(piece, gutters) if piece.glyphs else []
        if len(groups) <= 1:
            line = _line(children, page_height)
            if line is not None:
                placed.append((line, column_of(piece, gutters)))
            continue
        # Glyphs on both sides of a gutter and none inside it: one line per column. A
        # space or other non-glyph goes with the glyph before it.
        group_of = {glyph: number for number, group in enumerate(groups) for glyph in group}
        parts: list[list[LTItem]] = [[] for _ in groups]
        glyph = current = 0
        for child in children:
            if isinstance(child, LTChar):
                current = group_of[glyph]
                glyph += 1
            parts[current].append(child)
        for part in parts:
            line = _line(part, page_height)
            if line is not None:
                placed.append((line, column_of(_piece(part, page_height), gutters)))
    across = sorted((line for line, column in placed if column is None), key=lambda li: li.top)
    ordered: list[Line] = []
    for section in range(len(across) + 1):
        for column in range(len(gutters) + 1):
            ordered.extend(
                _rows(
                    [
                        line
                        for line, index in placed
                        if index == column and sum(a.top < line.top for a in across) == section
                    ]
                )
            )
        if section < len(across):
            ordered.append(across[section])
    return ordered


def _line(children: Sequence[LTItem], page_height: float) -> Line | None:
    """The line of text made of ``children``: a text line's glyphs, and the spaces
    pdfminer adds between words. None if it holds no text."""
    whole = "".join(c.get_text() for c in children if isinstance(c, LTChar | LTAnno))
    soft = " ".join(whole.split()).endswith(SOFT_HYPHEN)
    pieces: list[Text] = []
    style = (False, False)
    for child in children:
        if isinstance(child, LTChar):
            style = getattr(child, STYLE, (False, False))
        if isinstance(child, LTChar | LTAnno):  # glyphs, and the spaces between words
            pieces.append(Text(child.get_text(), *style))
    runs = styled_runs(pieces)
    text = "".join(run.text for run in runs)
    chars = [c for c in children if isinstance(c, LTChar)]
    if not text or not chars:
        return None
    plain = all(not run.bold and not run.italic for run in runs)
    size = Counter(round(c.size, 1) for c in chars).most_common(1)[0][0]
    x0, x1 = min(c.x0 for c in chars), max(c.x1 for c in chars)
    y0, y1 = min(c.y0 for c in chars), max(c.y1 for c in chars)
    named = all(_MONO_NAME.search(c.fontname) for c in chars)
    advance = _advance(chars)
    verbatim = normalise(whole).rstrip() if advance > 0 else ""
    return Line(
        text,
        x0,
        x1,
        page_height - y1,
        page_height - y0,
        size,
        soft,
        monospace=named,
        advance=advance,
        verbatim=verbatim,
        runs=() if plain else runs,
    )


_SPACE = re.compile(r"(\s+)")


def styled_runs(pieces: Iterable[Text]) -> tuple[Text, ...]:
    """Pieces of text with their styles, normalised (RFL-R8) and with whitespace collapsed
    to single spaces and trimmed, as maximal runs of one style. A space between two runs
    is bold (or italic) only when both runs are."""
    tokens: list[Text] = []
    groups: list[Text] = []
    for piece in pieces:
        if groups and (groups[-1].bold, groups[-1].italic) == (piece.bold, piece.italic):
            groups[-1] = Text(groups[-1].text + piece.text, piece.bold, piece.italic)
        else:
            groups.append(piece)
    for group in groups:
        for part in _SPACE.split(normalise(group.text)):
            if not part:
                continue
            if part.isspace():
                if tokens and tokens[-1].text != " ":
                    tokens.append(Text(" "))
            else:
                tokens.append(Text(part, group.bold, group.italic))
    if tokens and tokens[-1].text == " ":
        tokens.pop()
    for i, token in enumerate(tokens):
        if token.text == " " and 0 < i < len(tokens) - 1:
            before, after = tokens[i - 1], tokens[i + 1]
            tokens[i] = Text(" ", before.bold and after.bold, before.italic and after.italic)
    runs: list[Text] = []
    for token in tokens:
        if runs and (runs[-1].bold, runs[-1].italic) == (token.bold, token.italic):
            runs[-1] = Text(runs[-1].text + token.text, token.bold, token.italic)
        else:
            runs.append(token)
    return tuple(runs)


def _advance(chars: list[LTChar]) -> float:
    """The glyphs' common advance, or 0 if they don't share one."""
    advances = [c.adv for c in chars]
    if not advances or max(advances) <= 0:
        return 0.0
    return advances[0] if max(advances) - min(advances) <= MONO_SPREAD * max(advances) else 0.0


def _graphics(layout: LTPage, lines: list[Line]) -> Graphics:
    page_area = max(layout.width * layout.height, 1.0)
    sizes = Counter(line.size for line in lines)
    em = sizes.most_common(1)[0][0] if sizes else 10.0
    rules: list[Rule] = []
    # The area under shapes, as a coarse mask, so overlapping shapes count once.
    step = max(_MASK_STEP, max(layout.width, layout.height) / _MAX_MASK_EDGE)
    mask = np.zeros(
        (math.ceil(layout.height / step) + 1, math.ceil(layout.width / step) + 1), dtype=bool
    )
    for shape in _shapes(layout):
        x0, y0, x1, y1 = shape.bbox
        width, height = x1 - x0, y1 - y0
        if isinstance(shape, LTLine | LTRect) and min(width, height) <= _RULE_THICKNESS:
            if max(width, height) >= em:  # shorter ones are marks, not rules
                rules.append(Rule(x0, x1, layout.height - y1, layout.height - y0))
        elif isinstance(shape, LTImage):
            if width * height < _SCAN_SHARE * page_area:
                _cover(mask, shape.bbox, step)
        elif (
            isinstance(shape, LTCurve) and shape.fill
        ):  # an outline alone (a frame round a box) covers nothing
            _cover(mask, shape.bbox, step)
    covered = float(mask.mean())
    glyphs = maths = 0
    for item in _text_lines(layout):
        chars = [c for c in item if isinstance(c, LTChar) and not c.get_text().isspace()]
        if chars and (_advance(chars) > 0 or all(_MONO_NAME.search(c.fontname) for c in chars)):
            continue  # code: its symbols are not mathematics
        glyphs += len(chars)
        maths += sum(_is_math(c) for c in chars)
    return Graphics(rules, covered, glyphs, maths)


def _cover(mask: np.ndarray, bbox: tuple[float, float, float, float], step: float) -> None:
    x0, y0, x1, y1 = (max(0.0, value) / step for value in bbox)
    mask[int(y0) : math.ceil(y1), int(x0) : math.ceil(x1)] = True


def _shapes(item: LTItem) -> Iterator[LTComponent]:
    """Every image and vector shape on the page, inside figures too."""
    if isinstance(item, LTImage | LTCurve):  # LTLine and LTRect are LTCurves
        yield item
    elif isinstance(item, LTContainer) and not isinstance(item, LTTextContainer):
        for child in item:
            yield from _shapes(child)


def _text_lines(container: Iterable[LTItem]) -> Iterator[LTTextLine]:
    """Every text line on the page, inside figures too."""
    for element in container:
        if isinstance(element, LTTextLine):
            yield element
        elif isinstance(element, LTTextContainer | LTFigure):
            yield from _text_lines(element)


def _is_math(char: LTChar) -> bool:
    if _MATH_FONT.search(char.fontname):
        return True
    text = char.get_text()
    return len(text) == 1 and (
        unicodedata.category(text) == "Sm" or 0x1D400 <= ord(text) <= 0x1D7FF
    )


def _rows(lines: list[Line]) -> list[Line]:
    """Lines sorted top to bottom, with pieces of one line of text merged left to right.
    Pieces on the same row but further apart than a few ems (such as two columns) stay
    separate lines."""
    rows: list[list[Line]] = []
    for line in sorted(lines, key=lambda line: (line.top, line.x0)):
        if rows and _overlap(rows[-1][-1], line) > _SAME_ROW:
            rows[-1].append(line)
        else:
            rows.append([line])
    merged: list[Line] = []
    for row in rows:
        pieces: list[list[Line]] = []
        for line in sorted(row, key=lambda line: line.x0):
            if pieces and line.x0 - pieces[-1][-1].x1 <= _PIECE_GAP_EM * line.size:
                pieces[-1].append(line)
            else:
                pieces.append([line])
        merged.extend(_merge(piece) for piece in pieces)
    return merged


def _overlap(a: Line, b: Line) -> float:
    shared = min(a.bottom, b.bottom) - max(a.top, b.top)
    shorter = min(a.bottom - a.top, b.bottom - b.top)
    return shared / shorter if shorter > 0 else 0.0


def _merge(row: list[Line]) -> Line:
    if len(row) == 1:
        return row[0]
    runs: list[Text] = []
    for line in row:
        runs.extend([*([Text(" ")] if runs else []), *line.styled])
    merged = styled_runs(runs)
    plain = all(not run.bold and not run.italic for run in merged)
    advance = row[0].advance
    if any(abs(line.advance - advance) > MONO_SPREAD * advance for line in row):
        advance = 0.0
    verbatim = ""
    if advance > 0:
        # Keep the gaps between pieces of an equal-advance line as spaces (none when the
        # pieces touch).
        verbatim = row[0].verbatim
        for left, right in pairwise(row):
            spaces = max(0, round((right.x0 - left.x1) / advance))
            verbatim += " " * spaces + right.verbatim
    return Line(
        text=" ".join(line.text for line in row),
        x0=min(line.x0 for line in row),
        x1=max(line.x1 for line in row),
        top=min(line.top for line in row),
        bottom=max(line.bottom for line in row),
        size=max(row, key=lambda line: len(line.text)).size,
        soft_hyphen=row[-1].soft_hyphen,
        runs=() if plain else merged,
        monospace=all(line.monospace for line in row),
        advance=advance,
        verbatim=verbatim,
    )
