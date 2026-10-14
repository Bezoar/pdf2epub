"""Deciding whether, and with which password, a source PDF can be opened (PWD §1, §2).

The only decryption pdf2epub does is opening a PDF that uses the Standard security
handler with a password the user supplied (MAIN-R4). The ``/Encrypt`` dictionary is read
with pypdf, which needs no password for it; candidates are tried with pypdf's
``decrypt()``, which tells an owner-password match from a user-password one (PWD-R9).
"""

import dataclasses
import logging
import re
import zipfile
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import NoReturn

import pypdf
from pypdf import PasswordType
from pypdf.generic import DictionaryObject

from pdf2epub.issues import Issue, IssueCode
from pdf2epub.passwords import Candidate, Secret, SourceLabel, distinct

log = logging.getLogger(__name__)

MISSING_PASSWORD_HINT = "supply the password for this file"
DRM_PROTECTED_HINT = "open it in the vendor's reader; pdf2epub will not bypass DRM"
RESTRICTED_HINT = "supply the owner password"
UNSUPPORTED_ENCRYPTION_HINT = "this PDF's encryption is not supported"

# /P bit 5 (value 16): copy or otherwise extract text and graphics.
_EXTRACT = 16


@dataclass(frozen=True)
class Access:
    """How to open a source PDF."""

    password: Secret | None
    """The password to open it with; None when it needs none beyond the empty one."""
    source: SourceLabel | None
    """The label of the candidate that opened it, or that lifted its restrictions as the
    owner password; None when no password was needed (PWD-R24)."""
    owner_password_used: bool = False
    """True when an owner password lifted a copy/extract restriction (PWD-R11)."""


OPEN = Access(None, None)
"""Access to a file that needs no password."""


class AccessDenied(Exception):
    """The file can't be opened with what the user supplied; ``issue`` says why."""

    def __init__(self, issue: Issue) -> None:
        super().__init__(issue.message)
        self.issue = issue


def needs_password(path: Path) -> bool:
    """True when ``path`` is encrypted with the Standard security handler in a
    configuration pdf2epub can decrypt, so candidate passwords may apply to it. Any other
    file, an unreadable or refused one included, never gets as far as trying a password
    (PWD-R6)."""
    with _quiet_pypdf():
        try:
            return _open_encrypted(path) is not None
        except AccessDenied:
            return False
        except Exception:
            log.debug("could not read the encryption of %s", path, exc_info=True)
            return False


def unlock(path: Path, candidates: Sequence[Candidate]) -> Access:
    """Find how to open ``path``: as it is, with the empty password, or with the first of
    ``candidates`` (already in trial order) that opens it (PWD-R6). Raises
    ``AccessDenied`` when it is refused before any password is tried (PWD-R2 to PWD-R4),
    when none opens it (PWD-R7), or when the file forbids copying and extracting its
    content and no candidate is its owner password (PWD-R10, PWD-R11)."""
    with _quiet_pypdf():
        return _unlock(path, candidates)


def _unlock(path: Path, candidates: Sequence[Candidate]) -> Access:
    try:
        reader = _open_encrypted(path)
    except AccessDenied:
        raise
    except Exception:
        # Not readable by pypdf: the PDF libraries that convert it report the damage.
        log.debug("could not read the encryption of %s", path, exc_info=True)
        return OPEN
    if reader is None:
        return OPEN
    candidates = distinct(candidates)
    matched = reader.decrypt("")
    access, remaining = OPEN, candidates
    if matched is PasswordType.NOT_DECRYPTED:
        for index, candidate in enumerate(candidates):
            matched = reader.decrypt(candidate.secret.reveal())
            if matched is not PasswordType.NOT_DECRYPTED:
                access, remaining = (
                    Access(candidate.secret, candidate.source),
                    candidates[index + 1 :],
                )
                break
    if matched is PasswordType.NOT_DECRYPTED:
        _refuse_unopened(candidates)
    if _extraction_permitted(reader):
        return access
    if matched is PasswordType.OWNER_PASSWORD and access.password is not None:
        # A supplied owner password opened it: that lifts the restriction (PWD-R11). The
        # empty password never does (PWD-R10).
        return dataclasses.replace(access, owner_password_used=True)
    # MAIN-R6, PWD-R11: opened with a user password (or the empty one), but copying is
    # forbidden. Only the owner password lifts that; the remaining candidates are tried
    # as the owner password.
    for candidate in remaining:
        if reader.decrypt(candidate.secret.reveal()) is PasswordType.OWNER_PASSWORD:
            return Access(candidate.secret, candidate.source, owner_password_used=True)
    raise AccessDenied(
        Issue(
            IssueCode.RESTRICTED,
            "The PDF forbids copying or extracting its content, and no owner password "
            "was supplied for it.",
            hint=RESTRICTED_HINT,
        )
    )


def _open_encrypted(path: Path) -> pypdf.PdfReader | None:
    """Steps 1 to 3 of PWD-R6: None when ``path`` is not encrypted; a reader ready to try
    passwords on when it uses the Standard handler in a configuration pypdf can decrypt.
    Raises ``AccessDenied`` with ``drm_protected`` for a DRM wrapper or any other
    security handler (MAIN-R5, PWD-R2, PWD-R3), and with ``unsupported_encryption`` for a
    Standard configuration pypdf can't decrypt (PWD-R4). No password, not even the empty
    one, has been tried when it raises."""
    if is_drm_wrapper(path):
        raise AccessDenied(_drm_protected("The file is a DRM wrapper, not a PDF."))
    encrypt = _encrypt_dictionary(path)
    if encrypt is None:
        return None
    if encrypt.get("/Filter") != "/Standard":
        # Never try a password against any other security handler.
        raise AccessDenied(_drm_protected("The PDF is protected by a DRM security handler."))
    revision = encrypt.get("/R")
    if not isinstance(revision, int) or not _MIN_REVISION <= revision <= _MAX_REVISION:
        raise AccessDenied(_unsupported(f"revision {revision}"))
    try:
        # pypdf reads the crypt filters as it opens the file, and refuses those it can't
        # decrypt before it tries the empty password.
        return pypdf.PdfReader(path)
    except NotImplementedError as error:
        raise AccessDenied(_unsupported(str(error))) from error


# PWD-R1: the Standard security handler revisions pdf2epub decrypts.
_MIN_REVISION, _MAX_REVISION = 2, 6


class _StructureReader(pypdf.PdfReader):
    """A pypdf reader that leaves the file's encryption alone. pypdf's own reader refuses
    every handler but Standard, and tries the empty password, as it opens a file; the
    handler must be classified before either (PWD-R6). The ``/Encrypt`` dictionary is
    never itself encrypted, so it reads the same without decrypting anything."""

    def _handle_encryption(self, password: str | bytes | None) -> None:
        return None


def _encrypt_dictionary(path: Path) -> DictionaryObject | None:
    """The ``/Encrypt`` dictionary of ``path``; None when it is not encrypted. An
    ``/Encrypt`` entry that isn't a dictionary names no handler, which is not Standard."""
    reader = _StructureReader(path)
    if not reader.is_encrypted:
        return None
    encrypt = reader.trailer["/Encrypt"].get_object()
    return encrypt if isinstance(encrypt, DictionaryObject) else DictionaryObject()


def _drm_protected(message: str) -> Issue:
    return Issue(IssueCode.DRM_PROTECTED, message, hint=DRM_PROTECTED_HINT)


def _unsupported(detail: str) -> Issue:
    return Issue(
        IssueCode.UNSUPPORTED_ENCRYPTION,
        f"The PDF uses Standard-handler encryption that can't be decrypted ({detail}).",
        hint=UNSUPPORTED_ENCRYPTION_HINT,
    )


# PWD-R3: a Readium LCP package is a ZIP archive holding this licence document.
_LCP_LICENSE = "META-INF/license.lcpl"
# PWD-R3: an Adobe .acsm file is an XML fulfilment token in the ADEPT namespace.
_ACSM_ROOT = re.compile(rb"<(?:[A-Za-z_][\w.-]*:)?fulfillmentToken[\s/>]")
_ADEPT_NAMESPACE = b"http://ns.adobe.com/adept"
_ACSM_WINDOW = 4096


def is_drm_wrapper(path: Path) -> bool:
    """True when ``path`` is one of the DRM wrapper formats of PWD-R3: a Readium LCP
    archive or an Adobe ``.acsm`` fulfilment token. Only the layout is looked at; nothing
    in the wrapper is read beyond that."""
    try:
        with path.open("rb") as file:
            head = file.read(_ACSM_WINDOW)
        if head.lstrip(b"\xef\xbb\xbf \t\r\n").startswith(b"<"):
            return bool(_ACSM_ROOT.search(head)) and _ADEPT_NAMESPACE in head
        if not zipfile.is_zipfile(path):
            return False
        with zipfile.ZipFile(path) as archive:
            return _LCP_LICENSE in archive.namelist()
    except (OSError, ValueError, zipfile.BadZipFile):
        return False


def _refuse_unopened(candidates: Sequence[Candidate]) -> NoReturn:
    """Raise the issue for a file no candidate opened (PWD-R7, PWD-R8)."""
    if not candidates:
        raise AccessDenied(
            Issue(
                IssueCode.MISSING_PASSWORD,
                "The PDF is password-protected and no password was supplied for it.",
                hint=MISSING_PASSWORD_HINT,
            )
        )
    labels = ", ".join(candidate.source for candidate in candidates)
    raise AccessDenied(
        Issue(
            IssueCode.WRONG_PASSWORD,
            f"None of the passwords supplied opened the PDF; sources tried: {labels}.",
            hint=f"check the password; sources tried: {labels}",
        )
    )


def _extraction_permitted(reader: pypdf.PdfReader) -> bool:
    """True unless the ``/P`` permissions forbid copying or extracting content. A ``/P``
    that can't be read counts as forbidding it (fail closed, PWD-R9)."""
    encrypt = reader.trailer["/Encrypt"].get_object()
    permissions = encrypt.get("/P") if isinstance(encrypt, DictionaryObject) else None
    return isinstance(permissions, int) and bool(int(permissions) & _EXTRACT)


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
