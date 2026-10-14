"""Deciding whether, and with which password, a source PDF can be opened (PWD §1, §2).

The only decryption pdf2epub does is opening a PDF that uses the Standard security
handler with a password the user supplied (MAIN-R4). The ``/Encrypt`` dictionary is read
with pypdf, which needs no password for it; candidates are tried with pypdf's
``decrypt()``, which tells an owner-password match from a user-password one (PWD-R9).
"""

import dataclasses
import itertools
import logging
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import NoReturn

import pypdf
from pypdf import PasswordType
from pypdf.generic import DictionaryObject

from pdf2epub.issues import Issue, IssueCode
from pdf2epub.passwords import Candidate, Prompt, Secret, SourceLabel, distinct

log = logging.getLogger(__name__)

MISSING_PASSWORD_HINT = "supply the password for this file"
DRM_PROTECTED_HINT = "open it in the vendor's reader; pdf2epub will not bypass DRM"
RESTRICTED_HINT = "supply the owner password"

# /P bit 5 (value 16): copy or otherwise extract text and graphics.
_EXTRACT = 16

# PWD-R19: the most answers a prompt may give for one file.
PROMPT_ATTEMPTS = 3
PROMPT_LABEL: SourceLabel = "prompt"


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
    """The file can't be opened with what the user supplied; ``issue`` says why.

    ``password_helps`` is True when a password would let the conversion go ahead (it is
    missing, wrong, or the owner password is needed), and ``sources_tried`` then holds
    the labels of the candidates tried, in trial order, each once (PWD-R22)."""

    def __init__(
        self, issue: Issue, sources_tried: Sequence[SourceLabel] = (), password_helps: bool = False
    ) -> None:
        super().__init__(issue.message)
        self.issue = issue
        self.sources_tried = list(sources_tried)
        self.password_helps = password_helps


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


def unlock(path: Path, candidates: Sequence[Candidate], prompt: Prompt | None = None) -> Access:
    """Find how to open ``path``: as it is, with the empty password, or with the first of
    ``candidates`` (already in trial order) that opens it (PWD-R6), and then, if none
    does, with an answer to ``prompt`` (PWD-R12, step 5). Raises ``AccessDenied`` when
    nothing opens it (PWD-R7, PWD-R20), or when the file forbids copying and extracting
    its content and neither a candidate nor a prompt answer is its owner password
    (PWD-R10, PWD-R11).

    ``prompt`` is asked at most ``PROMPT_ATTEMPTS`` times for the file; an answer of
    None skips it. Each answer is a candidate labelled ``prompt``."""
    with _quiet_pypdf():
        return _unlock(path, candidates, _Prompter(path, prompt))


class _Prompter:
    """The prompt answers for one file, at most ``PROMPT_ATTEMPTS`` of them (PWD-R19),
    until one is skipped (PWD-R20)."""

    def __init__(self, path: Path, prompt: Prompt | None) -> None:
        self._path = path
        self._prompt = prompt
        self._attempt = 0
        self.tried = False
        """True once an answer was given, tried or not."""

    def __iter__(self) -> Iterator[Candidate]:
        while self._prompt is not None and self._attempt < PROMPT_ATTEMPTS:
            self._attempt += 1
            answer = self._prompt(self._path, self._attempt)
            if answer is None:
                self._prompt = None  # skipped: no more prompting for this file
                return
            self.tried = True
            yield Candidate(answer, PROMPT_LABEL)


def _unlock(path: Path, candidates: Sequence[Candidate], prompter: _Prompter) -> Access:
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
        for candidate in prompter:
            matched = reader.decrypt(candidate.secret.reveal())
            if matched is not PasswordType.NOT_DECRYPTED:
                access, remaining = Access(candidate.secret, candidate.source), []
                break
    if matched is PasswordType.NOT_DECRYPTED:
        _refuse_unopened(candidates, prompter.tried)
    if _extraction_permitted(reader):
        return access
    if matched is PasswordType.OWNER_PASSWORD and access.password is not None:
        # A supplied owner password opened it: that lifts the restriction (PWD-R11). The
        # empty password never does (PWD-R10).
        return dataclasses.replace(access, owner_password_used=True)
    # MAIN-R6, PWD-R11: opened with a user password (or the empty one), but copying is
    # forbidden. Only the owner password lifts that; the remaining candidates are tried
    # as the owner password.
    for candidate in itertools.chain(remaining, prompter):
        if reader.decrypt(candidate.secret.reveal()) is PasswordType.OWNER_PASSWORD:
            return Access(candidate.secret, candidate.source, owner_password_used=True)
    tried = [c.source for c in candidates] + ([PROMPT_LABEL] if prompter.tried else [])
    raise AccessDenied(
        Issue(
            IssueCode.RESTRICTED,
            "The PDF forbids copying or extracting its content, and no owner password "
            "was supplied for it.",
            hint=RESTRICTED_HINT,
        ),
        _labels(tried),
        password_helps=True,
    )


def _refuse_unopened(candidates: Sequence[Candidate], prompted: bool) -> NoReturn:
    """Raise the issue for a file that neither a candidate nor a prompt answer opened
    (PWD-R7, PWD-R8, PWD-R20)."""
    tried = _labels([c.source for c in candidates] + ([PROMPT_LABEL] if prompted else []))
    if not tried:
        raise AccessDenied(
            Issue(
                IssueCode.MISSING_PASSWORD,
                "The PDF is password-protected and no password was supplied for it.",
                hint=MISSING_PASSWORD_HINT,
            ),
            password_helps=True,
        )
    labels = ", ".join(tried)
    raise AccessDenied(
        Issue(
            IssueCode.WRONG_PASSWORD,
            f"None of the passwords supplied opened the PDF; sources tried: {labels}.",
            hint=f"check the password; sources tried: {labels}",
        ),
        tried,
        password_helps=True,
    )


def _labels(sources: Sequence[SourceLabel]) -> list[SourceLabel]:
    """``sources`` in order, each label once."""
    return list(dict.fromkeys(sources))


def _extraction_permitted(reader: pypdf.PdfReader) -> bool:
    """True unless the ``/P`` permissions forbid copying or extracting content. A ``/P``
    that can't be read counts as forbidding it (fail closed, PWD-R9)."""
    encrypt = reader.trailer["/Encrypt"].get_object()
    permissions = encrypt.get("/P") if isinstance(encrypt, DictionaryObject) else None
    return isinstance(permissions, int) and bool(int(permissions) & _EXTRACT)


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
