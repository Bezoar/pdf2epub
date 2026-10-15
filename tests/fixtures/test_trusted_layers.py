"""The must-trust fixture of #89 still reproduces what once got a real-world page rejected
(``fixturegen/trusted.py``), so ``test_every_must_trust_page_is_trusted`` (OCR-AC3) keeps
testing the fix rather than an easier page.
"""

from pathlib import Path

import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_c

from pdf2epub.ocr.textlayer import MAX_GARBAGE_RATIO

FIXTURES = Path(__file__).resolve().parent
TYPE3_NAMES = FIXTURES / "born-digital" / "type3-glyph-names.pdf"


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
