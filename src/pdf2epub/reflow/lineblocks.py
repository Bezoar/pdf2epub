"""Line blocks (RFL-R36): blocks whose line breaks carry meaning, such as verse or code.

A text block is a line block when every line is set in a monospace font, or when it has
at least three lines, most of them end well short of the column's right edge (ragged
right, where prose runs to the edge), and none ends in a word broken with a hyphen (which
only wrapped prose does). Its lines are kept as they are: they are never joined,
de-hyphenated or joined across pages. A monospace block also keeps its spaces: those in
the text layer and, for a line that starts right of the block's leftmost line, as many
more as fit in the gap.
"""

import re

from pdf2epub.reflow.extract import MONO_SPREAD
from pdf2epub.reflow.layout import TextBlock, Typography
from pdf2epub.reflow.model import Inline, LineBlock, Text

# A block needs at least this many lines to be verse rather than a short paragraph.
_MIN_LINES = 3
# A line ends well short when it stops at least this share of the column width before the
# column's right edge; a ragged block has more than this share of such lines.
_SHORT_SHARE, _RAGGED_SHARE = 0.2, 0.6
# A block whose glyphs all share one advance is monospace, whatever its font is called,
# when it has at least this many glyphs, of at least this many distinct characters: no
# proportional face sets that many different letters all the same width.
_MONO_GLYPHS, _MONO_DISTINCT = 10, 5
# A line ending in a hyphen after a letter breaks a word, as wrapped prose does.
_WORD_BREAK = re.compile(r"[^\W\d_][-\u2010]$")


def is_monospace(block: TextBlock) -> bool:
    """Every line of ``block`` is set in one monospace font: one named as monospace, or
    one whose glyphs all share an advance. Checked over the whole block, so short lines
    such as ``}`` count too."""
    lines = block.lines
    if all(line.monospace and line.advance > 0 for line in lines):
        return True
    advance = lines[0].advance
    if advance <= 0 or any(abs(line.advance - advance) > MONO_SPREAD * advance for line in lines):
        return False
    glyphs = "".join(line.text for line in lines).replace(" ", "")
    return len(glyphs) >= _MONO_GLYPHS and len(set(glyphs)) >= _MONO_DISTINCT


def is_line_block(block: TextBlock, typography: Typography) -> bool:
    if is_monospace(block):
        return True
    if len(block.lines) < _MIN_LINES or typography.is_display(block.size):
        return False
    if any(line.soft_hyphen or _WORD_BREAK.search(line.text) for line in block.lines):
        return False  # wrapped prose
    width = typography.right - typography.left
    if width <= 0:
        return False
    short = [line for line in block.lines if typography.right - line.x1 >= _SHORT_SHARE * width]
    return len(short) > _RAGGED_SHARE * len(block.lines)


def line_block(block: TextBlock) -> LineBlock:
    """The document-model line block for ``block``, which ``is_line_block``. Its lines keep
    their bold and italic runs (RFL-R22)."""
    if not is_monospace(block):
        return LineBlock([list(line.styled) for line in block.lines], monospace=False)
    left = min(line.x0 for line in block.lines)
    lines: list[list[Inline]] = []
    for line in block.lines:
        indent = round((line.x0 - left) / line.advance)
        lines.append(list(_restyle(" " * indent + line.verbatim, line.styled)))
    return LineBlock(lines, monospace=True)


def _restyle(text: str, runs: tuple[Text, ...]) -> list[Text]:
    """``text`` (a line's verbatim text, with its spaces kept) styled like ``runs`` (the
    same line with its spaces collapsed): the letters line up in order, and a space takes
    the style of the letter before it."""
    letters = [(run.bold, run.italic) for run in runs for c in run.text if not c.isspace()]
    styled: list[Text] = []
    style, n = (False, False), 0
    for char in text:
        if not char.isspace() and n < len(letters):
            style, n = letters[n], n + 1
        if styled and (styled[-1].bold, styled[-1].italic) == style:
            styled[-1] = Text(styled[-1].text + char, *style)
        else:
            styled.append(Text(char, *style))
    return styled or [Text(text)]
