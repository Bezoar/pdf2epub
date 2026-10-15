"""A born-digital fixture that the text-layer quality check must trust (OCR-AC3, TST-R4),
reproducing why a real-world smoke-set page was once rejected (#89).

- ``born-digital/type3-glyph-names.pdf``: ``textlayers``' 4-page book typeset in a Type 3
  bitmap font with no ``/ToUnicode`` map whose glyphs carry their standard names
  (``/a``, ``/comma``) at their WinAnsi codes, as Matplotlib writes the fonts of a figure
  saved as PDF (S4's figures). PDFium reports every one of its characters as a
  Unicode-map error, though each glyph's name says which character it is.

Its ground truth (the ``.txt`` beside the PDF) is the book's text without header and page
numbers: its paragraphs, separated by blank lines.
"""

from pathlib import Path

from fixturegen import textlayers

TYPE3_NAMES = "born-digital/type3-glyph-names.pdf"
TYPE3_NAMES_TRUTH = "born-digital/type3-glyph-names.txt"


def build_type3_names(out_dir: Path) -> None:
    pages, truth = textlayers._book()
    pdf = textlayers._no_tounicode(pages, standard_names=True)
    textlayers._write(out_dir, TYPE3_NAMES, TYPE3_NAMES_TRUTH, pdf, truth)
