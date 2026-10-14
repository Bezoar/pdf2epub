"""Signals that score a page's text (OCR-R7), used to choose a fallback page's hidden text
between the best OCR attempt and the page's own text layer (OCR-R10).

``garbage_ratio`` counts the characters that are certainly not text: U+FFFD, Private Use
Area code points and C0/C1 control characters. The text-layer quality check adds the
signals that need the PDF (Unicode-map errors) or the OCR language (script mismatch).
"""

import unicodedata

_REPLACEMENT = "�"


def garbage_ratio(text: str) -> float:
    """The share of ``text``'s non-space characters that are garbage; 0 for no text."""
    characters = [c for c in text if not c.isspace()]
    if not characters:
        return 0.0
    garbage = sum(c == _REPLACEMENT or unicodedata.category(c) in ("Co", "Cc") for c in characters)
    return garbage / len(characters)
