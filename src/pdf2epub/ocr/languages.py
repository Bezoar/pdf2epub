"""The OCR language (OCR-R26): ``OcrOptions.languages`` if set; else the book language
(``ConversionOptions.language``), else the PDF's declared language, each mapped from its
BCP 47 tag to a Tesseract code; else ``eng``.

The mapping is a built-in table (OP39) from a tag's primary language subtag, and its
script or region where Tesseract has separate data (``zh-Hant`` → ``chi_tra``,
``sr-Latn`` → ``srp_latn``). A tag the table doesn't know falls back to ``eng``.
"""

from pdf2epub.options import ConversionOptions

DEFAULT = "eng"

# ISO 639-1 codes (and a few deprecated or macrolanguage aliases) to the names of
# Tesseract's language data, for every language Tesseract ships data for.
_TESSERACT = {
    "af": "afr", "am": "amh", "ar": "ara", "as": "asm", "az": "aze", "be": "bel",
    "bg": "bul", "bn": "ben", "bo": "bod", "br": "bre", "bs": "bos", "ca": "cat",
    "co": "cos", "cs": "ces", "cy": "cym", "da": "dan", "de": "deu", "dv": "div",
    "dz": "dzo", "el": "ell", "en": "eng", "eo": "epo", "es": "spa", "et": "est",
    "eu": "eus", "fa": "fas", "fi": "fin", "fo": "fao", "fr": "fra", "fy": "fry",
    "ga": "gle", "gd": "gla", "gl": "glg", "gu": "guj", "he": "heb", "hi": "hin",
    "hr": "hrv", "ht": "hat", "hu": "hun", "hy": "hye", "id": "ind", "in": "ind",
    "is": "isl", "it": "ita", "iu": "iku", "iw": "heb", "ja": "jpn", "jv": "jav",
    "ka": "kat", "kk": "kaz", "km": "khm", "kn": "kan", "ko": "kor", "ku": "kmr",
    "ky": "kir", "la": "lat", "lb": "ltz", "lo": "lao", "lt": "lit", "lv": "lav",
    "mi": "mri", "mk": "mkd", "ml": "mal", "mn": "mon", "mr": "mar", "ms": "msa",
    "mt": "mlt", "my": "mya", "nb": "nor", "ne": "nep", "nl": "nld", "nn": "nor",
    "no": "nor", "oc": "oci", "or": "ori", "pa": "pan", "pl": "pol", "ps": "pus",
    "pt": "por", "qu": "que", "ro": "ron", "ru": "rus", "sa": "san", "sd": "snd",
    "si": "sin", "sk": "slk", "sl": "slv", "sq": "sqi", "sr": "srp", "su": "sun",
    "sv": "swe", "sw": "swa", "ta": "tam", "te": "tel", "tg": "tgk", "th": "tha",
    "ti": "tir", "to": "ton", "tr": "tur", "tt": "tat", "ug": "uig", "uk": "ukr",
    "ur": "urd", "uz": "uzb", "vi": "vie", "yi": "yid", "yo": "yor", "zh": "chi_sim",
}  # fmt: skip
# Languages with no ISO 639-1 code, whose BCP 47 tag is already Tesseract's name.
_THREE_LETTER = frozenset({"ceb", "chr", "fil", "grc", "kmr", "syr"})
# Tesseract's separate data for a script or region of a language, by (language, subtag).
_VARIANTS = {
    ("zh", "hant"): "chi_tra", ("zh", "tw"): "chi_tra", ("zh", "hk"): "chi_tra",
    ("zh", "mo"): "chi_tra", ("sr", "latn"): "srp_latn", ("az", "cyrl"): "aze_cyrl",
    ("uz", "cyrl"): "uzb_cyrl",
}  # fmt: skip


def tesseract_code(tag: str) -> str | None:
    """The Tesseract language code for BCP 47 ``tag`` (``de-DE`` → ``deu``), or None
    if the table doesn't know it."""
    subtags = tag.strip().replace("_", "-").lower().split("-")
    language = subtags[0]
    for subtag in subtags[1:]:
        if (language, subtag) in _VARIANTS:
            return _VARIANTS[language, subtag]
    if language in _THREE_LETTER:
        return language
    return _TESSERACT.get(language)


def ocr_languages(options: ConversionOptions, declared: str | None) -> str:
    """The OCR language string for a conversion under ``options`` of a PDF whose declared
    language is ``declared`` (OCR-R26)."""
    if options.ocr.languages:
        return options.ocr.languages
    tag = options.language or declared
    if not tag:
        return DEFAULT
    return tesseract_code(tag) or DEFAULT
