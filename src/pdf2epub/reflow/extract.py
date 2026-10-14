"""Per-page text extraction with pdfminer.six (RFL-R1, RFL-R7) and text normalisation
(RFL-R8).

Each page comes out as its text lines in reading order (top to bottom), with their
geometry and font size: layout analysis (``reflow.layout``) groups them into blocks and
paragraphs. A line's text is normalised; a soft hyphen at its end is removed from the
text but kept as a flag, so de-hyphenation still sees the word break (RFL-R17). A line
also keeps its runs of bold and italic text (RFL-R22).
"""

import re
import unicodedata
from collections import Counter
from collections.abc import Iterable, Iterator
from dataclasses import dataclass

from pdfminer.layout import LAParams, LTChar, LTTextContainer, LTTextLine

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
class PageText:
    """The text lines of one page, top to bottom."""

    page: int
    """1-based PDF page index."""
    width: float
    height: float
    lines: list[Line]


def normalise(text: str) -> str:
    """Unicode NFC, with ligatures expanded, soft hyphens removed and characters that XML
    can't carry dropped (RFL-R8)."""
    text = text.translate(LIGATURES).replace(SOFT_HYPHEN, "")
    return _NOT_XML.sub("", unicodedata.normalize("NFC", text))


def read_pages(pdf: ParsedPdf) -> Iterator[PageText]:
    """Yield each page's text lines, one page at a time."""
    for number, layout in enumerate(pdf.layouts(LAParams()), start=1):
        lines: list[Line] = []
        for element in layout:
            if isinstance(element, LTTextContainer):
                for item in element:
                    if isinstance(item, LTTextLine):
                        line = _line(item, layout.height)
                        if line is not None:
                            lines.append(line)
        yield PageText(number, layout.width, layout.height, _rows(lines))


def _line(item: LTTextLine, page_height: float) -> Line | None:
    raw = " ".join(item.get_text().split())
    soft = raw.endswith(SOFT_HYPHEN)
    chars: list[Text] = []
    style = (False, False)
    for obj in item:
        if isinstance(obj, LTChar):
            style = getattr(obj, STYLE, (False, False))
        chars.append(Text(obj.get_text(), *style))
    runs = styled_runs(chars)
    text = "".join(run.text for run in runs)
    if not text:
        return None
    sizes = Counter(round(c.size, 1) for c in item if isinstance(c, LTChar))
    size = sizes.most_common(1)[0][0] if sizes else item.height
    x0, y0, x1, y1 = item.bbox
    plain = all(not run.bold and not run.italic for run in runs)
    return Line(text, x0, x1, page_height - y1, page_height - y0, size, soft, () if plain else runs)


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
    return Line(
        text=" ".join(line.text for line in row),
        x0=min(line.x0 for line in row),
        x1=max(line.x1 for line in row),
        top=min(line.top for line in row),
        bottom=max(line.bottom for line in row),
        size=max(row, key=lambda line: len(line.text)).size,
        soft_hyphen=row[-1].soft_hyphen,
        runs=() if plain else merged,
    )
