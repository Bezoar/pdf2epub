"""The per-language wordlists shipped with pdf2epub (RFL-R17).

Each is ``pdf2epub/wordlists/<language>.txt`` (UTF-8, NFC, one word per line), with a
``<language>.source.toml`` provenance sidecar."""

import functools
import re
from importlib import resources

_PRIMARY = re.compile(r"^([a-z]{2,3})(?:-|$)")


@functools.cache
def wordlist(language: str) -> frozenset[str] | None:
    """The wordlist for a BCP 47 language tag (by its primary subtag), or None if pdf2epub
    has none for that language."""
    match = _PRIMARY.match(language.lower())
    if match is None:
        return None
    path = resources.files("pdf2epub").joinpath("wordlists", f"{match.group(1)}.txt")
    if not path.is_file():
        return None
    return frozenset(path.read_text(encoding="utf-8").splitlines())
