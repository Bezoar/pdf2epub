"""Deciding whether, and with which password, a source PDF can be opened (PWD §1, §2).

The only decryption pdf2epub does is opening a PDF that uses the Standard security
handler with a password the user supplied (MAIN-R4). The ``/Encrypt`` dictionary is read
with pypdf, which needs no password for it; candidates are tried with pypdf's
``decrypt()``, which tells an owner-password match from a user-password one (PWD-R9).
"""

import logging
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import pypdf
from pypdf import PasswordType
from pypdf.generic import DictionaryObject

from pdf2epub.issues import Issue, IssueCode
from pdf2epub.passwords import Candidate, Secret, SourceLabel, distinct

log = logging.getLogger(__name__)

MISSING_PASSWORD_HINT = "supply the password for this file"
DRM_PROTECTED_HINT = "open it in the vendor's reader; pdf2epub will not bypass DRM"


@dataclass(frozen=True)
class Access:
    """How to open a source PDF."""

    password: Secret | None
    """The password to open it with; None when it needs none beyond the empty one."""
    source: SourceLabel | None
    """The label of the candidate that opened it, or None (PWD-R24)."""


OPEN = Access(None, None)
"""Access to a file that needs no password."""


class AccessDenied(Exception):
    """The file can't be opened with what the user supplied; ``issue`` says why."""

    def __init__(self, issue: Issue) -> None:
        super().__init__(issue.message)
        self.issue = issue


def needs_password(path: Path) -> bool:
    """True when ``path`` is encrypted with the Standard security handler, so candidate
    passwords may apply to it. Any other file, an unreadable one included, never gets as
    far as trying a password."""
    try:
        with _quiet_pypdf():
            reader = pypdf.PdfReader(path)
            return reader.is_encrypted and _filter(reader) == "/Standard"
    except Exception:
        log.debug("could not read the encryption of %s", path, exc_info=True)
        return False


def unlock(path: Path, candidates: Sequence[Candidate]) -> Access:
    """Find how to open ``path``: as it is, with the empty password, or with the first of
    ``candidates`` (already in trial order) that opens it (PWD-R6). Raises
    ``AccessDenied`` when none does (PWD-R7)."""
    with _quiet_pypdf():
        return _unlock(path, candidates)


def _unlock(path: Path, candidates: Sequence[Candidate]) -> Access:
    try:
        reader = pypdf.PdfReader(path)
        encrypted = reader.is_encrypted
    except Exception:
        # Not readable by pypdf: the PDF libraries that convert it report the damage.
        log.debug("could not read the encryption of %s", path, exc_info=True)
        return OPEN
    if not encrypted:
        return OPEN
    if _filter(reader) != "/Standard":
        # MAIN-R5, PWD-R2: never try a password against any other security handler.
        raise AccessDenied(
            Issue(
                IssueCode.DRM_PROTECTED,
                "The PDF is protected by a DRM security handler.",
                hint=DRM_PROTECTED_HINT,
            )
        )
    if reader.decrypt("") is not PasswordType.NOT_DECRYPTED:
        return OPEN
    for candidate in distinct(candidates):
        if reader.decrypt(candidate.secret.reveal()) is not PasswordType.NOT_DECRYPTED:
            return Access(candidate.secret, candidate.source)
    if not candidates:
        raise AccessDenied(
            Issue(
                IssueCode.MISSING_PASSWORD,
                "The PDF is password-protected and no password was supplied for it.",
                hint=MISSING_PASSWORD_HINT,
            )
        )
    labels = ", ".join(candidate.source for candidate in distinct(candidates))
    raise AccessDenied(
        Issue(
            IssueCode.WRONG_PASSWORD,
            f"None of the passwords supplied opened the PDF; sources tried: {labels}.",
            hint=f"check the password; sources tried: {labels}",
        )
    )


def _filter(reader: pypdf.PdfReader) -> object:
    """The ``/Filter`` of the ``/Encrypt`` dictionary: the security handler's name."""
    encrypt = reader.trailer["/Encrypt"].get_object()
    return encrypt.get("/Filter") if isinstance(encrypt, DictionaryObject) else None


@contextmanager
def _quiet_pypdf() -> Iterator[None]:
    """Hold back pypdf's warnings about damage while it reads the encryption: the PDF
    libraries that convert the file report damage as issues (RFL-R2)."""
    logger = logging.getLogger("pypdf")
    level = logger.level
    logger.setLevel(logging.ERROR)
    try:
        yield
    finally:
        logger.setLevel(level)
