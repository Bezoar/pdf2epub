"""Generate the English wordlist used by de-hyphenation (RFL-R17) and the text-layer
quality check: ``src/pdf2epub/wordlists/en.txt``, its provenance sidecar
``en.source.toml`` and its licence notice ``en.LICENSE``.

The words come from SCOWLv2 (Spell Checker Oriented Word Lists, since renamed the English
Speller Database) by Kevin Atkinson, at a pinned release, verified by SHA-256. The script
builds the release's SQLite database with its own tools and extracts the default speller
size (60) in American, British (-ise and -ize) and Canadian spelling, without the
Australian spelling and region and without special categories. A list of size 80 or
below, without Australian English, is covered by the release's main notice alone (its
``Copyright`` file, shipped as ``en.LICENSE``).

The list is NFC, one word per line, sorted by code point, with no duplicates.

Usage: ``uv run python scripts/wordlist_en.py`` (needs network access; writes into the
package). Running it again with the same pin gives the same files.
"""

from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unicodedata
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "src" / "pdf2epub" / "wordlists"

SOURCE = "SCOWLv2 (now the English Speller Database)"
SOURCE_URL = "https://github.com/en-wl/wordlist"
VERSION = "rel-2026.02.25"
COMMIT = "7e99edab8e32f9f9ea2b15f249ca8d4d67237410"
ARCHIVE_URL = f"https://codeload.github.com/en-wl/wordlist/tar.gz/refs/tags/{VERSION}"
ARCHIVE_SHA256 = "74e7cc3e9e03e609c1c74bb7e8862fcd988cdd64768dcbee4611581b7e633852"
# SCOWL's notice is a permissive, HPND-style licence that SPDX does not list, so the list
# carries it as a LicenseRef with the full text beside it.
LICENSE = "LicenseRef-SCOWL"
WORD_LIST_ARGS = ["word-list", "60", "A,B,Z,C", "1", "--regions", "US,GB,CA", "--categories="]


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def download(work: Path) -> Path:
    with urllib.request.urlopen(ARCHIVE_URL, timeout=120) as response:
        data: bytes = response.read()
    if sha256(data) != ARCHIVE_SHA256:
        raise SystemExit(f"{ARCHIVE_URL}: SHA-256 {sha256(data)} != pinned {ARCHIVE_SHA256}")
    archive = work / "esdb.tar.gz"
    archive.write_bytes(data)
    with tarfile.open(archive) as tar:
        tar.extractall(work / "src", filter="data")
    (root,) = (work / "src").iterdir()
    return root


def extract_words(root: Path) -> list[str]:
    python = sys.executable
    subprocess.run([python, "combine.py", "create-db", "scowl.db"], cwd=root, check=True)
    proc = subprocess.run(
        [python, "scowl", "--db", "scowl.db", *WORD_LIST_ARGS],
        cwd=root,
        check=True,
        capture_output=True,
    )
    words = {unicodedata.normalize("NFC", w) for w in proc.stdout.decode("utf-8").splitlines()}
    return sorted(w for w in words if w and not any(c.isspace() for c in w))


def sidecar(words: list[str], digest: str) -> str:
    options = " ".join(WORD_LIST_ARGS)
    return f"""\
# Provenance of en.txt, written by {Path(__file__).relative_to(REPO).as_posix()}.
language = "en"
source = "{SOURCE}"
source_url = "{SOURCE_URL}"
version = "{VERSION}"
commit = "{COMMIT}"
archive_url = "{ARCHIVE_URL}"
archive_sha256 = "{ARCHIVE_SHA256}"
license = "{LICENSE}"
license_file = "en.LICENSE"
generator = "{Path(__file__).relative_to(REPO).as_posix()}"
generator_options = "{options}"
words = {len(words)}
sha256 = "{digest}"
"""


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        root = download(Path(tmp))
        words = extract_words(root)
        OUT.mkdir(parents=True, exist_ok=True)
        data = "".join(f"{w}\n" for w in words).encode("utf-8")
        (OUT / "en.txt").write_bytes(data)
        shutil.copyfile(root / "Copyright", OUT / "en.LICENSE")
        (OUT / "en.source.toml").write_text(sidecar(words, sha256(data)), encoding="utf-8")
    print(f"wrote {len(words)} words to {OUT / 'en.txt'}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
