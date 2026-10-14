"""The synthetic fixture inventory (TST-R3): every group and fixture TST-R3 lists is
committed, and the encrypted fixtures carry the encryption TST-AC2 names.

Each TST-R3 fixture is mapped to its file here by hand, from the spec's wording and the
fixture generators' docstrings (``fixturegen/``). The encryption is read with pypdf
straight from each file's ``/Encrypt`` dictionary.
"""

from pathlib import Path
from typing import Any

import pytest
from pypdf import PasswordType, PdfReader
from pypdf.constants import UserAccessPermissions
from pypdf.generic import DictionaryObject

FIXTURES = Path(__file__).resolve().parent

INVENTORY: dict[str, dict[str, str]] = {
    "Born-digital": {
        "multi-chapter novel with an outline, headers, footers, page numbers, split "
        "paragraphs and hyphenation": "born-digital/novel.pdf",
        "the novel without an outline": "born-digital/novel-no-outline.pdf",
        "two-column page set": "born-digital/two-column.pdf",
        "a page with a table and a page with math": "born-digital/complex-pages.pdf",
        "blank page": "born-digital/blank-page.pdf",
        "italic and bold runs": "born-digital/headings.pdf",
        "verse-and-code sample": "born-digital/verse-and-code.pdf",
    },
    "Scanned": {
        "the novel at 300 DPI (clean)": "scanned/novel-clean.pdf",
        "with noise": "scanned/novel-noise.pdf",
        "with 2 degree skew": "scanned/novel-skew.pdf",
        "with 90 degree rotation": "scanned/novel-rotated.pdf",
        "at 150 DPI": "scanned/novel-150dpi.pdf",
        "image-only scan with no text layer": "scanned/image-only.pdf",
        "scan with a good invisible OCR layer": "scanned/ocr-layer.pdf",
    },
    "Encrypted": {
        "AES-256 (R6) user password": "encrypted/aes256-user.pdf",
        "AES-128 (R4) user password": "encrypted/aes128-user.pdf",
        "RC4-128 (R3) user password": "encrypted/rc4-128-user.pdf",
        "owner password only, copy/extract forbidden": "encrypted/owner-only-restricted.pdf",
        "owner password only, all permissions": "encrypted/owner-only-all-permissions.pdf",
        "non-Standard security handler": "encrypted/fopn-foweb.pdf",
    },
    "Must reject (text layer)": {
        "font with no ToUnicode map": "must-reject/no-tounicode.pdf",
        "garbled invisible OCR layer": "must-reject/garbled-layer.pdf",
        "invisible OCR layer covering half of each page": "must-reject/half-layer.pdf",
    },
    "Damaged": {
        "truncated file": "damaged/truncated.pdf",
        "repairable cross-reference table": "damaged/novel-no-xref.pdf",
        "non-PDF file with a .pdf name": "damaged/not-a-pdf.pdf",
        "zero-page document": "damaged/zero-pages.pdf",
        "image over the decompression limits": "damaged/image-bomb.pdf",
    },
    "Page numbers": {
        "one printed page missing": "scanned/page-numbers-missing.pdf",
        "one printed page repeated": "scanned/page-numbers-repeated.pdf",
        "roman front matter and an unnumbered chapter opener": (
            "scanned/page-numbers-front-matter.pdf"
        ),
    },
}


def missing(inventory: dict[str, dict[str, str]]) -> list[str]:
    return [
        f"{group}: {name} ({path})"
        for group, fixtures in inventory.items()
        for name, path in fixtures.items()
        if not (FIXTURES / path).is_file()
    ]


@pytest.mark.ac("TST-AC2")
def test_every_tst_r3_fixture_is_committed() -> None:
    assert missing(INVENTORY) == []


class _Unopened(PdfReader):
    """A reader that leaves the ``/Encrypt`` dictionary as it is, whatever its handler:
    pypdf itself refuses to open a non-Standard handler."""

    def _handle_encryption(self, password: Any) -> None:
        pass


def encrypt_dictionary(path: str) -> dict[str, Any]:
    reader = _Unopened(FIXTURES / path)
    encrypt = reader.trailer["/Encrypt"].get_object()
    assert isinstance(encrypt, DictionaryObject)
    entries: dict[str, Any] = dict(encrypt)
    filters = encrypt.get("/CF")
    if filters is not None:
        stream = filters.get_object()[encrypt["/StmF"]].get_object()
        entries["/CFM"] = stream.get("/CFM")
    return entries


EXTRACT = int(UserAccessPermissions.EXTRACT)


@pytest.mark.ac("TST-AC2")
@pytest.mark.parametrize(
    ("path", "revision", "version", "length", "method"),
    [
        ("encrypted/aes256-user.pdf", 6, 5, 256, "/AESV3"),
        ("encrypted/aes128-user.pdf", 4, 4, 128, "/AESV2"),
        ("encrypted/rc4-128-user.pdf", 3, 2, 128, None),
        ("encrypted/owner-only-restricted.pdf", 6, 5, 256, "/AESV3"),
        ("encrypted/owner-only-all-permissions.pdf", 6, 5, 256, "/AESV3"),
    ],
)
def test_standard_fixtures_have_the_expected_revision_and_algorithm(
    path: str, revision: int, version: int, length: int, method: str | None
) -> None:
    encrypt = encrypt_dictionary(path)
    assert encrypt["/Filter"] == "/Standard"
    assert (encrypt["/R"], encrypt["/V"], encrypt.get("/Length", 40)) == (
        revision,
        version,
        length,
    )
    assert encrypt.get("/CFM") == method


@pytest.mark.ac("TST-AC2")
@pytest.mark.parametrize(
    ("path", "opens_with_empty_password", "extract_allowed"),
    [
        ("encrypted/aes256-user.pdf", False, True),
        ("encrypted/aes128-user.pdf", False, True),
        ("encrypted/rc4-128-user.pdf", False, True),
        ("encrypted/owner-only-restricted.pdf", True, False),
        ("encrypted/owner-only-all-permissions.pdf", True, True),
    ],
)
def test_user_and_owner_passwords_and_permissions(
    path: str, opens_with_empty_password: bool, extract_allowed: bool
) -> None:
    reader = PdfReader(FIXTURES / path)
    opened = reader.decrypt("") != PasswordType.NOT_DECRYPTED
    assert opened is opens_with_empty_password
    permissions = int(encrypt_dictionary(path)["/P"])
    assert bool(permissions & EXTRACT) is extract_allowed
    if extract_allowed:
        # "All permissions": every permission bit pypdf knows is set.
        assert permissions & int(UserAccessPermissions.all()) == int(UserAccessPermissions.all())


@pytest.mark.ac("TST-AC2")
def test_the_non_standard_handler_fixture_names_a_vendor_filter() -> None:
    encrypt = encrypt_dictionary("encrypted/fopn-foweb.pdf")
    assert encrypt["/Filter"] not in ("/Standard", None)
    with pytest.raises(NotImplementedError):
        PdfReader(FIXTURES / "encrypted/fopn-foweb.pdf")
