"""The password-protected fixtures (TST-R3, "Encrypted"): the two-page book, encrypted
with the Standard security handler and a user password, all permissions granted.

- ``encrypted/aes256-user.pdf``: AES-256 (R6);
- ``encrypted/aes128-user.pdf``: AES-128 (R4);
- ``encrypted/rc4-128-user.pdf``: RC4-128 (R3).

Each has its own user and owner passwords (below). They are published test passwords,
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

from fixturegen import twopage

AES256 = "encrypted/aes256-user.pdf"
AES256_TRUTH = "encrypted/aes256-user.txt"
AES128 = "encrypted/aes128-user.pdf"
AES128_TRUTH = "encrypted/aes128-user.txt"
RC4_128 = "encrypted/rc4-128-user.pdf"
RC4_128_TRUTH = "encrypted/rc4-128-user.txt"

# (user password, owner password) of each fixture.
PASSWORDS = {
    AES256: ("hunter2", "aes256-owner"),
    AES128: ("aes128-user", "aes128-owner"),
    RC4_128: ("rc4-user", "rc4-owner"),
}
ALGORITHMS = {AES256: "AES-256", AES128: "AES-128", RC4_128: "RC4-128"}


def build_aes256(out_dir: Path) -> None:
    _build(out_dir, AES256, AES256_TRUTH)


def build_aes128(out_dir: Path) -> None:
    _build(out_dir, AES128, AES128_TRUTH)


def build_rc4_128(out_dir: Path) -> None:
    _build(out_dir, RC4_128, RC4_128_TRUTH)


def _build(out_dir: Path, path: str, truth: str) -> None:
    with tempfile.TemporaryDirectory() as scratch:
        twopage.build(Path(scratch))
        plain = Path(scratch) / twopage.PATH
        ground_truth = (Path(scratch) / twopage.GROUND_TRUTH).read_bytes()
        writer = pypdf.PdfWriter(clone_from=plain)
    user, owner = PASSWORDS[path]
    with _seeded_randomness(path):
        writer.encrypt(user, owner, algorithm=ALGORITHMS[path])
        pdf_path = out_dir / path
        pdf_path.parent.mkdir(parents=True, exist_ok=True)
        with pdf_path.open("wb") as file:
            writer.write(file)
    (out_dir / truth).write_bytes(ground_truth)


@contextmanager
def _seeded_randomness(seed: str) -> Iterator[None]:
    generator = random.Random(seed)

    def token_bytes(count: int | None = None) -> bytes:
        return generator.randbytes(32 if count is None else count)

    # pypdf calls it through the ``secrets`` module, so patching the module covers both
    # its key derivation and its AES provider.
    with mock.patch("secrets.token_bytes", token_bytes):
        yield
