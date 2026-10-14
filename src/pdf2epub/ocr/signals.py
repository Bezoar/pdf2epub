"""Signals that score text (OCR-R7): the text-layer quality check (``ocr.textlayer``) uses
them on a page's existing text layer, and a fallback page's hidden text is chosen by them
between the best OCR attempt and that layer (OCR-R10).

- **Garbage**: characters that are certainly not text: U+FFFD, Private Use Area code
  points, C0/C1 control characters, and letters of a script that does not match the OCR
  language. (The text-layer check also counts PDFium's Unicode-map errors, which only
  the PDF can tell.)
- **Word plausibility**: the share of word tokens found in the language's wordlist (the
  one de-hyphenation uses); with no wordlist, the share that look like words: letters
  only, of a sensible length.

Scripts are told apart by Unicode character names (``LATIN SMALL LETTER A``,
``CYRILLIC CAPITAL LETTER A``, ``CJK UNIFIED IDEOGRAPH-4E00``). Han, kana, Hangul and
Bopomofo count as one script, ``CJK``, because East Asian books mix them. Latin letters
in plain ASCII are allowed in any language (names, abbreviations, units), but accented
Latin letters only in a language written in Latin script: in a Russian book, ``Ïðèâåò`` is
mojibake.
"""

import functools
import re
import unicodedata
from collections.abc import Collection

from pdf2epub.ocr.languages import known_codes

_REPLACEMENT = "�"
CJK = "CJK"
# The first word of a Unicode letter's name, for the scripts told apart.
_SCRIPTS = {
    "LATIN": "LATIN",
    "GREEK": "GREEK",
    "COPTIC": "GREEK",
    "CYRILLIC": "CYRILLIC",
    "ARMENIAN": "ARMENIAN",
    "HEBREW": "HEBREW",
    "ARABIC": "ARABIC",
    "SYRIAC": "SYRIAC",
    "THAANA": "THAANA",
    "DEVANAGARI": "DEVANAGARI",
    "BENGALI": "BENGALI",
    "GURMUKHI": "GURMUKHI",
    "GUJARATI": "GUJARATI",
    "ORIYA": "ORIYA",
    "TAMIL": "TAMIL",
    "TELUGU": "TELUGU",
    "KANNADA": "KANNADA",
    "MALAYALAM": "MALAYALAM",
    "SINHALA": "SINHALA",
    "THAI": "THAI",
    "LAO": "LAO",
    "TIBETAN": "TIBETAN",
    "MYANMAR": "MYANMAR",
    "GEORGIAN": "GEORGIAN",
    "ETHIOPIC": "ETHIOPIC",
    "KHMER": "KHMER",
    "MONGOLIAN": "MONGOLIAN",
    "CHEROKEE": "CHEROKEE",
    "CJK": CJK,
    "HIRAGANA": CJK,
    "KATAKANA": CJK,
    "HANGUL": CJK,
    "BOPOMOFO": CJK,
}
# Scripts written without spaces between words: a run of them is one token.
_UNSPACED = frozenset({CJK, "THAI", "LAO", "KHMER", "MYANMAR", "TIBETAN"})
# The scripts of Tesseract languages not written in Latin script; every other language
# Tesseract knows (``ocr.languages``) is written in Latin script.
_LANGUAGE_SCRIPTS = {
    **dict.fromkeys(
        ("rus", "ukr", "bel", "bul", "mkd", "srp", "kaz", "kir", "tgk", "tat", "mon"),
        "CYRILLIC",
    ),
    **dict.fromkeys(("uzb_cyrl", "aze_cyrl"), "CYRILLIC"),
    **dict.fromkeys(("ell", "grc"), "GREEK"),
    **dict.fromkeys(("ara", "fas", "urd", "pus", "snd", "uig"), "ARABIC"),
    **dict.fromkeys(("heb", "yid"), "HEBREW"),
    **dict.fromkeys(("hin", "mar", "nep", "san"), "DEVANAGARI"),
    **dict.fromkeys(("ben", "asm"), "BENGALI"),
    **dict.fromkeys(("bod", "dzo"), "TIBETAN"),
    **dict.fromkeys(("amh", "tir"), "ETHIOPIC"),
    **dict.fromkeys(
        ("jpn", "jpn_vert", "chi_sim", "chi_sim_vert", "chi_tra", "chi_tra_vert", "kor"), CJK
    ),
    "kor_vert": CJK,
    "pan": "GURMUKHI",
    "guj": "GUJARATI",
    "ori": "ORIYA",
    "tam": "TAMIL",
    "tel": "TELUGU",
    "kan": "KANNADA",
    "mal": "MALAYALAM",
    "sin": "SINHALA",
    "tha": "THAI",
    "lao": "LAO",
    "mya": "MYANMAR",
    "kat": "GEORGIAN",
    "hye": "ARMENIAN",
    "khm": "KHMER",
    "chr": "CHEROKEE",
    "syr": "SYRIAC",
    "div": "THAANA",
}
# Tesseract's script data (``script/Latin``) and other codes that are no language.
_NOT_LANGUAGES = frozenset({"osd", "equ"})
MAX_WORD_LENGTH = 30
"""With no wordlist, a token of more letters than this (outside scripts written without
spaces) doesn't look like a word."""
# A token: letters and digits, with apostrophes or hyphens inside it.
_APOSTROPHE = "\N{RIGHT SINGLE QUOTATION MARK}"
_TOKEN = re.compile(r"[^\W_]+(?:['\-" + _APOSTROPHE + r"][^\W_]+)*")


@functools.cache
def script(character: str) -> str | None:
    """The script of a letter, as told apart here; None for anything else."""
    if not unicodedata.category(character).startswith("L"):
        return None
    words = unicodedata.name(character, "").split()
    if words[:1] in (["FULLWIDTH"], ["HALFWIDTH"]):
        words = words[1:]
    return _SCRIPTS.get(words[0]) if words else None


def language_scripts(languages: str) -> frozenset[str] | None:
    """The scripts the OCR ``languages`` (``eng+fra``) are written in; None when one of them
    is not a language this table knows (custom model data), so scripts aren't checked."""
    scripts: set[str] = set()
    for code in languages.split("+"):
        if code in _NOT_LANGUAGES:
            continue
        if code in _LANGUAGE_SCRIPTS:
            scripts.add(_LANGUAGE_SCRIPTS[code])
        elif code in known_codes():
            scripts.add("LATIN")
        else:
            return None
    return frozenset(scripts) or None


@functools.cache
def is_garbage(character: str, scripts: frozenset[str] | None = None) -> bool:
    """Whether ``character`` is certainly not text in a book written in ``scripts``
    (scripts not checked when None)."""
    if character == _REPLACEMENT or unicodedata.category(character) in ("Co", "Cc"):
        return True
    if scripts is None:
        return False
    found = script(character)
    if found is None or found in scripts:
        return False
    return not (found == "LATIN" and character.isascii())


def garbage_ratio(text: str, scripts: frozenset[str] | None = None) -> float:
    """The share of ``text``'s non-space characters that are garbage; 0 for no text."""
    characters = [c for c in text if not c.isspace()]
    if not characters:
        return 0.0
    return sum(is_garbage(c, scripts) for c in characters) / len(characters)


def tokens(text: str) -> list[str]:
    """The word tokens of ``text``: runs of letters and digits (apostrophes and hyphens
    inside them kept) holding at least one letter."""
    return [t for t in _TOKEN.findall(text) if any(c.isalpha() for c in t)]


def plausibility(text: str, words: Collection[str] | None) -> tuple[float, int]:
    """The share of ``text``'s word tokens that are plausible words, and how many tokens
    there are (share 0 for none). With a wordlist, a token is plausible when it is in the
    list, as written, in lower case or capitalised (each part of a hyphenated token);
    without one, when it is letters only and of a sensible length."""
    found = tokens(text)
    if not found:
        return 0.0, 0
    check = _known if words is not None else _word_like
    plausible = sum(check(token, words) for token in found)
    return plausible / len(found), len(found)


def _known(token: str, words: Collection[str] | None) -> bool:
    assert words is not None
    token = token.replace(_APOSTROPHE, "'")
    return all(
        part in words or part.lower() in words or part.capitalize() in words
        for part in token.split("-")
    )


def _word_like(token: str, words: Collection[str] | None) -> bool:
    letters = [c for c in token if c not in ("'", "-", _APOSTROPHE)]
    if not all(c.isalpha() for c in letters):
        return False
    return len(letters) <= MAX_WORD_LENGTH or any(script(c) in _UNSPACED for c in letters)
