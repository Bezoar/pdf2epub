"""The shipped wordlists' layout and provenance (#35's local AC, #53): each language is
``pdf2epub/wordlists/<language>.txt`` (UTF-8, NFC, one word per line, sorted, no
duplicates) with a ``<language>.source.toml`` sidecar naming its source URL, version,
SPDX licence, generation script and SHA-256, and a licence that is MIT-compatible."""

import hashlib
import tomllib
import unicodedata
import zipfile
from importlib import resources
from importlib.resources.abc import Traversable
from pathlib import Path

import pytest
from test_package import ALLOWED_SPDX, Built, built  # noqa: F401  (``built`` is a fixture)

REPO = Path(__file__).resolve().parents[2]
WORDLISTS = resources.files("pdf2epub").joinpath("wordlists")
LANGUAGES = sorted(
    entry.name.removesuffix(".txt") for entry in WORDLISTS.iterdir() if entry.name.endswith(".txt")
)
SIDECAR_KEYS = {"source_url", "version", "license", "generator", "sha256"}
# Licences that SPDX doesn't list, reviewed as MIT-compatible, by LicenseRef and a phrase
# their shipped text must contain. SCOWL's notice is a permissive, HPND-style licence.
REVIEWED_LICENSE_REFS = {
    "LicenseRef-SCOWL": "Permission to use, copy, modify, distribute, and sell any part of "
    "SCOWLv2, or word lists created from it, is hereby granted without fee",
}


def entry(name: str) -> Traversable:
    return WORDLISTS.joinpath(name)


def test_english_ships_a_wordlist() -> None:
    assert "en" in LANGUAGES


@pytest.mark.parametrize("language", LANGUAGES)
def test_wordlist_is_nfc_sorted_unique_one_word_per_line(language: str) -> None:
    data = entry(f"{language}.txt").read_bytes()
    text = data.decode("utf-8")  # strict: fails on anything but UTF-8
    assert text.endswith("\n") and not text.startswith("﻿")
    words = text.removesuffix("\n").split("\n")
    assert len(words) > 1000
    assert [w for w in words if not w or any(c.isspace() for c in w)] == []
    assert [w for w in words if not unicodedata.is_normalized("NFC", w)] == []
    assert words == sorted(words)
    assert len(set(words)) == len(words)


@pytest.mark.parametrize("language", LANGUAGES)
def test_sidecar_describes_the_list(language: str) -> None:
    data = entry(f"{language}.txt").read_bytes()
    sidecar = tomllib.loads(entry(f"{language}.source.toml").read_text(encoding="utf-8"))

    assert sidecar.keys() >= SIDECAR_KEYS
    assert sidecar["sha256"] == hashlib.sha256(data).hexdigest()
    assert sidecar["words"] == data.count(b"\n")
    assert sidecar["source_url"].startswith("https://")
    assert (REPO / sidecar["generator"]).is_file()


@pytest.mark.parametrize("language", LANGUAGES)
def test_licence_is_mit_compatible_and_its_notice_ships(language: str) -> None:
    sidecar = tomllib.loads(entry(f"{language}.source.toml").read_text(encoding="utf-8"))
    licence = sidecar["license"]

    if licence.lower() in ALLOWED_SPDX:
        return
    assert licence in REVIEWED_LICENSE_REFS, f"{licence} is not a reviewed licence"
    notice = entry(sidecar["license_file"]).read_text(encoding="utf-8")
    assert REVIEWED_LICENSE_REFS[licence] in " ".join(notice.split())


def test_wheel_ships_the_wordlists_with_their_sidecars_and_notices(built: Built) -> None:  # noqa: F811
    with zipfile.ZipFile(built.wheel) as wheel:
        names = set(wheel.namelist())
    for language in LANGUAGES:
        sidecar = tomllib.loads(entry(f"{language}.source.toml").read_text(encoding="utf-8"))
        for name in (f"{language}.txt", f"{language}.source.toml", sidecar["license_file"]):
            assert f"pdf2epub/wordlists/{name}" in names
