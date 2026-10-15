"""The must-trust fixtures of #89 still reproduce what once got real-world pages rejected
(``fixturegen/trusted.py``), so ``test_every_must_trust_page_is_trusted`` (OCR-AC3) keeps
testing the fix rather than an easier page.
"""

import re
from pathlib import Path

import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_c

from pdf2epub.ocr.textlayer import MAX_GARBAGE_RATIO, MIN_PLAUSIBILITY, MIN_TOKENS
from pdf2epub.reflow.wordlists import wordlist

FIXTURES = Path(__file__).resolve().parent
TYPE3_NAMES = FIXTURES / "born-digital" / "type3-glyph-names.pdf"
LOREM_IPSUM = FIXTURES / "born-digital" / "lorem-ipsum.pdf"


def test_pdfium_finds_no_unicode_for_the_type3_fonts_characters() -> None:
    document = pdfium.PdfDocument(TYPE3_NAMES)
    try:
        for page in document:
            textpage = page.get_textpage()
            raw = textpage.raw
            characters = [
                index
                for index in range(pdfium_c.FPDFText_CountChars(raw))
                if not chr(pdfium_c.FPDFText_GetUnicode(raw, index)).isspace()
                and pdfium_c.FPDFText_IsGenerated(raw, index) != 1
            ]
            errors = [i for i in characters if pdfium_c.FPDFText_HasUnicodeMapError(raw, i) == 1]
            assert characters
            # Map errors alone would make the page garbled.
            assert len(errors) / len(characters) > MAX_GARBAGE_RATIO
            textpage.close()
            page.close()
    finally:
        document.close()


def test_few_of_the_lorem_ipsum_words_are_english() -> None:
    words = wordlist("en")
    assert words is not None
    text = LOREM_IPSUM.with_suffix(".txt").read_text(encoding="utf-8")
    tokens = re.findall(r"[A-Za-z]+", text)
    english = [t for t in tokens if t in words or t.lower() in words]
    assert len(tokens) >= MIN_TOKENS
    # The wordlist alone would find the page's words implausible.
    assert len(english) / len(tokens) < MIN_PLAUSIBILITY
