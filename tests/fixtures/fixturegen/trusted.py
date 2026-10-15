"""Born-digital fixtures that the text-layer quality check must trust (OCR-AC3, TST-R4),
each reproducing why a real-world smoke-set page was once rejected (#89).

- ``born-digital/type3-glyph-names.pdf``: ``textlayers``' 4-page book typeset in a Type 3
  bitmap font with no ``/ToUnicode`` map whose glyphs carry their standard names
  (``/a``, ``/comma``) at their WinAnsi codes, as Matplotlib writes the fonts of a figure
  saved as PDF (S4's figures). PDFium reports every one of its characters as a
  Unicode-map error, though each glyph's name says which character it is;
- ``born-digital/lorem-ipsum.pdf``: a page of Lorem Ipsum filler, the classic passage,
  typeset in Times-Roman in a book that declares English (``/Lang en``), as S6 (LaTeX)
  and S12 (LibreOffice) are. Its words are word-shaped but few are English.

Each ground truth (the ``.txt`` beside the PDF) is the book's text without header and page
numbers: its paragraphs, separated by blank lines.
"""

from pathlib import Path

from reportlab.pdfbase.pdfmetrics import stringWidth

from fixturegen import textlayers

TYPE3_NAMES = "born-digital/type3-glyph-names.pdf"
TYPE3_NAMES_TRUTH = "born-digital/type3-glyph-names.txt"
LOREM_IPSUM = "born-digital/lorem-ipsum.pdf"
LOREM_IPSUM_TRUTH = "born-digital/lorem-ipsum.txt"

# The classic Lorem Ipsum passage (after Cicero, De finibus 1.10.32), in two paragraphs.
_LOREM = (
    "Lorem ipsum dolor sit amet, consectetur adipiscing elit, sed do eiusmod tempor "
    "incididunt ut labore et dolore magna aliqua. Ut enim ad minim veniam, quis nostrud "
    "exercitation ullamco laboris nisi ut aliquip ex ea commodo consequat. Duis aute irure "
    "dolor in reprehenderit in voluptate velit esse cillum dolore eu fugiat nulla pariatur. "
    "Excepteur sint occaecat cupidatat non proident, sunt in culpa qui officia deserunt "
    "mollit anim id est laborum.",
    "Sed ut perspiciatis unde omnis iste natus error sit voluptatem accusantium doloremque "
    "laudantium, totam rem aperiam, eaque ipsa quae ab illo inventore veritatis et quasi "
    "architecto beatae vitae dicta sunt explicabo. Nemo enim ipsam voluptatem quia voluptas "
    "sit aspernatur aut odit aut fugit, sed quia consequuntur magni dolores eos qui ratione "
    "voluptatem sequi nesciunt. Neque porro quisquam est, qui dolorem ipsum quia dolor sit "
    "amet, consectetur, adipisci velit, sed quia non numquam eius modi tempora incidunt ut "
    "labore et dolore magnam aliquam quaerat voluptatem.",
)


def build_type3_names(out_dir: Path) -> None:
    pages, truth = textlayers._book()
    pdf = textlayers._no_tounicode(pages, standard_names=True)
    textlayers._write(out_dir, TYPE3_NAMES, TYPE3_NAMES_TRUTH, pdf, truth)


def build_lorem_ipsum(out_dir: Path) -> None:
    """One page: a running header, the two paragraphs (first lines indented) and a folio."""
    header = stringWidth(textlayers.TITLE, textlayers.HEADER_FONT, textlayers.SMALL_SIZE)
    folio = stringWidth("1", textlayers.BODY_FONT, textlayers.SMALL_SIZE)
    runs = [
        textlayers._Run(
            textlayers.HEADER_FONT,
            textlayers.SMALL_SIZE,
            (textlayers.PAGE_WIDTH - header) / 2,
            textlayers.HEADER_Y,
            textlayers.TITLE,
        )
    ]
    y = textlayers.BODY_TOP
    for paragraph in _LOREM:
        for index, line in enumerate(textlayers._break_lines(paragraph)):
            x = textlayers.MARGIN_X + (textlayers.INDENT if index == 0 else 0)
            runs.append(textlayers._Run(textlayers.BODY_FONT, textlayers.BODY_SIZE, x, y, line))
            y -= textlayers.LEADING
    runs.append(
        textlayers._Run(
            textlayers.BODY_FONT,
            textlayers.SMALL_SIZE,
            (textlayers.PAGE_WIDTH - folio) / 2,
            textlayers.FOLIO_Y,
            "1",
        )
    )
    truth = "\n\n".join(_LOREM) + "\n"
    textlayers._write(out_dir, LOREM_IPSUM, LOREM_IPSUM_TRUTH, textlayers._typeset([runs]), truth)
