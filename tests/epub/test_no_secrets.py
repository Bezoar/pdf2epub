"""The EPUB carries no encryption, DRM, password, password source, permission flags or
OCR engine details (EPUB-R3). The EPUBs come from the CLI, run as a subprocess, and are
read back from disk."""

import os
import re
import shutil
import subprocess
import sys
import zipfile
from collections.abc import Callable
from pathlib import Path

import pytest
from conftest import FIXTURES
from lxml import etree
from pypdf import PdfReader
from pypdf.generic import DictionaryObject

PDF2EPUB = Path(sys.executable).with_name("pdf2epub")
ENCRYPTED = FIXTURES / "encrypted"
# Published fixture passwords (tests/fixtures/fixturegen/encrypted.py).
AES256, AES256_PASSWORD = ENCRYPTED / "aes256-user.pdf", "hunter2"
RESTRICTED, OWNER_PASSWORD = ENCRYPTED / "owner-only-restricted.pdf", "restricted-owner"
Convert = Callable[[Path], tuple[Path, list[str], list[str]]]


def run_cli(args: list[str], cwd: Path, env_password: str | None = None) -> None:
    env = {k: v for k, v in os.environ.items() if k != "PDF2EPUB_PASSWORD"}
    if env_password is not None:
        env["PDF2EPUB_PASSWORD"] = env_password
    done = subprocess.run(
        [str(PDF2EPUB), *args], cwd=cwd, env=env, capture_output=True, text=True, check=False
    )
    assert done.returncode == 0, done.stderr


def permissions(pdf: Path) -> list[str]:
    """The PDF's ``/P`` value in both 32-bit forms: signed, as the PDF specification
    writes it, and unsigned, as some writers (pypdf among them) store it."""
    encrypt = PdfReader(pdf).trailer["/Encrypt"].get_object()
    assert isinstance(encrypt, DictionaryObject)
    unsigned = int(str(encrypt["/P"])) & 0xFFFFFFFF
    signed = unsigned - (1 << 32) if unsigned & 0x80000000 else unsigned
    return [str(signed), str(unsigned)]


def mentions(text: str, number: str) -> bool:
    """True when ``number`` appears in ``text`` as a whole number, not as part of a
    longer one."""
    return re.search(rf"(?<![\w.-]){re.escape(number)}(?![\w.])", text) is not None


def generated_text(archive: zipfile.ZipFile) -> dict[str, str]:
    """What pdf2epub itself writes into the EPUB, by member: every file but the chapter
    files whole, and from each chapter file only its element names and attributes (the
    book text copied from the PDF is left out)."""
    found: dict[str, str] = {}
    for name in archive.namelist():
        data = archive.read(name)
        if not name.endswith(".xhtml") or name.endswith("nav.xhtml"):
            found[name] = data.decode("utf-8", errors="replace")
            continue
        parts = []
        for element in etree.fromstring(data).iter():
            if isinstance(element.tag, str):
                parts.append(element.tag)
                parts.extend(str(key) + "=" + str(value) for key, value in element.attrib.items())
        found[name] = "\n".join(parts)
    return found


def convert_aes256(folder: Path) -> tuple[Path, list[str], list[str]]:
    shutil.copyfile(AES256, folder / "book.pdf")
    run_cli(["book.pdf"], folder, env_password=AES256_PASSWORD)
    return folder / "book.epub", [AES256_PASSWORD, "env"], permissions(AES256)


def convert_restricted(folder: Path) -> tuple[Path, list[str], list[str]]:
    shutil.copyfile(RESTRICTED, folder / "book.pdf")
    (folder / "passwords.toml").write_text(f'"book.pdf" = "{OWNER_PASSWORD}"\n')
    (folder / "passwords.toml").chmod(0o600)
    run_cli(["--password-map", "passwords.toml", "book.pdf"], folder)
    return folder / "book.epub", [OWNER_PASSWORD, 'map:"book.pdf"'], permissions(RESTRICTED)


@pytest.mark.ac("EPUB-AC3")
@pytest.mark.parametrize(
    "convert", [convert_aes256, convert_restricted], ids=["aes256-env", "owner-restricted-map"]
)
def test_the_epub_records_no_password_source_or_permissions(
    tmp_path: Path, convert: Convert
) -> None:
    epub, secrets, flags = convert(tmp_path)

    with zipfile.ZipFile(epub) as archive:
        names = archive.namelist()
        assert "META-INF/encryption.xml" not in names
        assert "META-INF/rights.xml" not in names
        generated = generated_text(archive)

    assert any(name.endswith(".opf") for name in generated)
    for name, text in generated.items():
        for secret in secrets:
            assert secret not in text, f"{secret!r} in {name}"
        for flag in flags:
            assert not mentions(text, flag), f"/P {flag} in {name}"
    [opf] = [text for name, text in generated.items() if name.endswith(".opf")]
    assert "tesseract" not in opf.lower()
