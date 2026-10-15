"""The password-protected fixtures (TST-R3, "Encrypted"): the two-page book, encrypted
with the Standard security handler and a user password, all permissions granted.

- ``encrypted/aes256-user.pdf``: AES-256 (R6);
- ``encrypted/aes128-user.pdf``: AES-128 (R4);
- ``encrypted/rc4-128-user.pdf``: RC4-128 (R3).

And the permission fixtures, all AES-256 (R6):

- ``encrypted/owner-only-restricted.pdf``: owner password only (opens with the empty
  password), copy/extract forbidden (``/P`` bit 5 clear);
- ``encrypted/owner-only-all-permissions.pdf``: owner password only, every permission
  granted;
- ``encrypted/user-owner-restricted.pdf``: a user and an owner password, copy/extract
  forbidden;
- ``encrypted/owner-only-padded.pdf``: as ``owner-only-restricted.pdf``, but its ``/O``
  and ``/U`` strings are zero-padded from 48 to 127 bytes, as qpdf's
  ``enc-XI-R6,V5,O=master.pdf`` (smoke entry S11) has them. Readers use only the first
  48 bytes, but pdfminer.six hashed the whole ``/U`` into the owner-password check, so
  the owner password was refused (#87);
- ``encrypted/owner-only-padded-r5.pdf``: the same with AES-256 R5 (the deprecated
  revision), whose key salts pdfminer.six hashes whole.

Each has its own user and owner passwords (below); the owner-only ones have an empty
user password. They are published test passwords,
not user secrets (TST-R9). Each ground truth is the two-page book's.

pypdf draws the encryption salts, file keys and AES initialisation vectors from
``secrets.token_bytes``; the generator replaces that with a seeded generator while it
writes, so the files are byte-identical from run to run.
"""

import random
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

import pypdf
from pypdf.constants import UserAccessPermissions
from pypdf.generic import ByteStringObject, NameObject

from fixturegen import twopage

AES256 = "encrypted/aes256-user.pdf"
AES256_TRUTH = "encrypted/aes256-user.txt"
AES128 = "encrypted/aes128-user.pdf"
AES128_TRUTH = "encrypted/aes128-user.txt"
RC4_128 = "encrypted/rc4-128-user.pdf"
RC4_128_TRUTH = "encrypted/rc4-128-user.txt"
OWNER_RESTRICTED = "encrypted/owner-only-restricted.pdf"
OWNER_RESTRICTED_TRUTH = "encrypted/owner-only-restricted.txt"
OWNER_ALL = "encrypted/owner-only-all-permissions.pdf"
OWNER_ALL_TRUTH = "encrypted/owner-only-all-permissions.txt"
USER_OWNER_RESTRICTED = "encrypted/user-owner-restricted.pdf"
USER_OWNER_RESTRICTED_TRUTH = "encrypted/user-owner-restricted.txt"
OWNER_PADDED = "encrypted/owner-only-padded.pdf"
OWNER_PADDED_TRUTH = "encrypted/owner-only-padded.txt"
OWNER_PADDED_R5 = "encrypted/owner-only-padded-r5.pdf"
OWNER_PADDED_R5_TRUTH = "encrypted/owner-only-padded-r5.txt"

# (user password, owner password) of each fixture.
PASSWORDS = {
    AES256: ("hunter2", "aes256-owner"),
    AES128: ("aes128-user", "aes128-owner"),
    RC4_128: ("rc4-user", "rc4-owner"),
    OWNER_RESTRICTED: ("", "restricted-owner"),
    OWNER_ALL: ("", "permissive-owner"),
    USER_OWNER_RESTRICTED: ("locked-user", "locked-owner"),
    OWNER_PADDED: ("", "padded-owner"),
    OWNER_PADDED_R5: ("", "padded-r5-owner"),
}
ALGORITHMS = {
    AES256: "AES-256",
    AES128: "AES-128",
    RC4_128: "RC4-128",
    OWNER_RESTRICTED: "AES-256",
    OWNER_ALL: "AES-256",
    USER_OWNER_RESTRICTED: "AES-256",
    OWNER_PADDED: "AES-256",
    OWNER_PADDED_R5: "AES-256-R5",
}
# Copy/extract forbidden: every permission but bit 5 (PWD-R10).
NO_EXTRACT = UserAccessPermissions.all() & ~UserAccessPermissions.EXTRACT
PERMISSIONS = {
    OWNER_RESTRICTED: NO_EXTRACT,
    USER_OWNER_RESTRICTED: NO_EXTRACT,
    OWNER_PADDED: NO_EXTRACT,
    OWNER_PADDED_R5: NO_EXTRACT,
}
# The length qpdf pads ``/O`` and ``/U`` to in an AES-256 file (ISO 32000-2 gives 48).
PADDED_LENGTH = 127


def build_aes256(out_dir: Path) -> None:
    _build(out_dir, AES256, AES256_TRUTH)


def build_aes128(out_dir: Path) -> None:
    _build(out_dir, AES128, AES128_TRUTH)


def build_rc4_128(out_dir: Path) -> None:
    _build(out_dir, RC4_128, RC4_128_TRUTH)


def build_owner_restricted(out_dir: Path) -> None:
    _build(out_dir, OWNER_RESTRICTED, OWNER_RESTRICTED_TRUTH)


def build_owner_all(out_dir: Path) -> None:
    _build(out_dir, OWNER_ALL, OWNER_ALL_TRUTH)


def build_user_owner_restricted(out_dir: Path) -> None:
    _build(out_dir, USER_OWNER_RESTRICTED, USER_OWNER_RESTRICTED_TRUTH)


def build_owner_padded(out_dir: Path) -> None:
    _build(out_dir, OWNER_PADDED, OWNER_PADDED_TRUTH, pad_to=PADDED_LENGTH)


def build_owner_padded_r5(out_dir: Path) -> None:
    _build(out_dir, OWNER_PADDED_R5, OWNER_PADDED_R5_TRUTH, pad_to=PADDED_LENGTH)


def _build(out_dir: Path, path: str, truth: str, pad_to: int | None = None) -> None:
    with tempfile.TemporaryDirectory() as scratch:
        twopage.build(Path(scratch))
        plain = Path(scratch) / twopage.PATH
        ground_truth = (Path(scratch) / twopage.GROUND_TRUTH).read_bytes()
        writer = pypdf.PdfWriter(clone_from=plain)
    user, owner = PASSWORDS[path]
    with _seeded_randomness(path):
        writer.encrypt(
            user,
            owner,
            permissions_flag=PERMISSIONS.get(path, UserAccessPermissions.all()),
            algorithm=ALGORITHMS[path],
        )
        if pad_to is not None:
            _pad_hashes(writer, pad_to)
        pdf_path = out_dir / path
        pdf_path.parent.mkdir(parents=True, exist_ok=True)
        with pdf_path.open("wb") as file:
            writer.write(file)
    (out_dir / truth).write_bytes(ground_truth)


def _pad_hashes(writer: pypdf.PdfWriter, length: int) -> None:
    """Zero-pad the Encrypt dictionary's ``/O`` and ``/U`` strings to ``length`` bytes.
    The key is already derived, so only what the file says changes."""
    entry = writer._encrypt_entry
    assert entry is not None
    for key in ("/O", "/U"):
        value = entry[key]
        assert isinstance(value, ByteStringObject)
        entry[NameObject(key)] = ByteStringObject(bytes(value).ljust(length, b"\0"))


@contextmanager
def _seeded_randomness(seed: str) -> Iterator[None]:
    generator = random.Random(seed)

    def token_bytes(count: int | None = None) -> bytes:
        return generator.randbytes(32 if count is None else count)

    # pypdf calls it through the ``secrets`` module, so patching the module covers both
    # its key derivation and its AES provider.
    with mock.patch("secrets.token_bytes", token_bytes):
        yield
