"""Deciding whether, and with which password, a source PDF can be opened (PWD §1, §2).

The only decryption pdf2epub does is opening a PDF that uses the Standard security
handler with a password the user supplied (MAIN-R4). The ``/Encrypt`` dictionary is read
with pypdf, which needs no password for it; candidates are tried with pypdf's
``decrypt()``, which tells an owner-password match from a user-password one (PWD-R9).
"""

import dataclasses
import itertools
import logging
import zipfile
from collections.abc import Iterator, Sequence
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, NoReturn
from xml.parsers import expat

import pypdf
from pypdf import PasswordType
from pypdf.generic import DictionaryObject

from pdf2epub.issues import Issue, IssueCode
from pdf2epub.passwords import Candidate, Prompt, Secret, SourceLabel, distinct

log = logging.getLogger(__name__)

MISSING_PASSWORD_HINT = "supply the password for this file"
DRM_PROTECTED_HINT = "open it in the vendor's reader; pdf2epub will not bypass DRM"
RESTRICTED_HINT = "supply the owner password"
UNSUPPORTED_ENCRYPTION_HINT = "this PDF's encryption is not supported"

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


def unlock(path: Path, candidates: Sequence[Candidate], prompt: Prompt | None = None) -> Access:
    """Find how to open ``path``: as it is, with the empty password, or with the first of
    ``candidates`` (already in trial order) that opens it (PWD-R6), and then, if none
    does, with an answer to ``prompt`` (PWD-R12, step 5). Raises ``AccessDenied`` when
    it is refused before any password is tried (PWD-R2 to PWD-R4), when nothing opens it
    (PWD-R7, PWD-R20), or when the file forbids copying and extracting its content and
    neither a candidate nor a prompt answer is its owner password (PWD-R10, PWD-R11).

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
        self.seen: set[Secret] = set()
        """The values tried already, the supplied candidates' included: an answer that
        repeats one uses up an attempt but is not tried again (PWD-R12)."""
        self.tried = False
        """True once an answer with a new value was tried."""

    def __iter__(self) -> Iterator[Candidate]:
        while self._prompt is not None and self._attempt < PROMPT_ATTEMPTS:
            self._attempt += 1
            answer = self._prompt(self._path, self._attempt)
            if answer is None:
                self._prompt = None  # skipped: no more prompting for this file
                return
            if answer in self.seen:
                continue
            self.seen.add(answer)
            self.tried = True
            yield Candidate(answer, PROMPT_LABEL)


def _unlock(path: Path, candidates: Sequence[Candidate], prompter: _Prompter) -> Access:
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
    prompter.seen.update(candidate.secret for candidate in candidates)
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
    problem = _crypt_filter_problem(encrypt)
    if problem is not None:
        raise AccessDenied(_unsupported(problem))
    try:
        # pypdf reads the crypt filters as it opens the file, and refuses those it can't
        # decrypt before it tries the empty password.
        return pypdf.PdfReader(path)
    except NotImplementedError as error:
        raise AccessDenied(_unsupported(str(error))) from error


# PWD-R1: the Standard security handler revisions pdf2epub decrypts.
_MIN_REVISION, _MAX_REVISION = 2, 6
# PWD-R1: the algorithm versions (/V) it decrypts: RC4 (1, 2), crypt filters (4, 5).
_ALGORITHMS = (1, 2, 4, 5)
# The crypt filter methods (/CFM) pypdf decrypts: RC4, AES-128, AES-256.
_METHODS = ("/V2", "/AESV2", "/AESV3")


def _crypt_filter_problem(encrypt: DictionaryObject) -> str | None:
    """Why the Standard ``encrypt`` dictionary can't be decrypted, read from its
    algorithm and crypt filters alone; None when nothing there stops it."""
    version = encrypt.get("/V", 0)
    if not isinstance(version, int) or version not in _ALGORITHMS:
        return f"algorithm /V {version}"
    if version < 4:
        return None
    filters = encrypt.get("/CF")
    filters = filters.get_object() if filters is not None else DictionaryObject()
    for key in ("/StmF", "/StrF", "/EFF"):
        name = encrypt.get(key, "/Identity")
        if name == "/Identity":
            continue
        crypt_filter = filters.get(name) if isinstance(filters, DictionaryObject) else None
        crypt_filter = crypt_filter.get_object() if crypt_filter is not None else None
        if not isinstance(crypt_filter, DictionaryObject):
            return f"{key} names no crypt filter: {name}"
        method = crypt_filter.get("/CFM")
        if method not in _METHODS:
            return f"{key} crypt filter method {method}"
    return None


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


def _xml_root(file: BinaryIO) -> str | None:
    """The root element's name, as ``<namespace> <local name>``, of the XML document
    ``file`` holds; None when it isn't well-formed XML up to its root's start tag, has a
    DTD, or has no root within the first ``_XML_PROLOG_LIMIT`` bytes. Parsing stops at a
    DTD, so no entity is ever expanded, and at the root's start tag."""
    roots: list[str] = []

    def start(name: str, attributes: object) -> None:
        roots.append(name)
        raise _StopParsing

    def doctype(*_: object) -> None:
        raise _StopParsing  # an .acsm token has no DTD; refuse to read anyone's entities

    parser = expat.ParserCreate(namespace_separator=" ")
    parser.StartElementHandler = start
    parser.StartDoctypeDeclHandler = doctype
    with suppress(_StopParsing, expat.ExpatError):
        read = 0
        while read < _XML_PROLOG_LIMIT and (chunk := file.read(_XML_CHUNK)):
            read += len(chunk)
            parser.Parse(chunk, False)
        # Expat may hold back a start tag until more input comes (reparse deferral);
        # ending the input makes it report what it has.
        parser.Parse(b"", True)
    return roots[0] if roots else None


class _StopParsing(Exception):
    """Stops parsing at the root element's start tag, or at a DTD."""


# PWD-R3: a Readium LCP package is a ZIP archive holding this licence document.
_LCP_LICENSE = "META-INF/license.lcpl"
# PWD-R3: an Adobe .acsm file is an XML fulfilment token in the ADEPT namespace.
_ACSM_ROOT = "http://ns.adobe.com/adept fulfillmentToken"
_XML_CHUNK = 4096
# How far into an XML file its root element is looked for: comments and processing
# instructions may come first, but not without end.
_XML_PROLOG_LIMIT = 1 << 20


def is_drm_wrapper(path: Path) -> bool:
    """True when ``path`` is one of the DRM wrapper formats of PWD-R3: a Readium LCP
    archive or an Adobe ``.acsm`` fulfilment token. Only the layout is looked at; nothing
    in the wrapper is read beyond that."""
    try:
        if zipfile.is_zipfile(path):
            with zipfile.ZipFile(path) as archive:
                return _LCP_LICENSE in archive.namelist()
        # Expat works out the encoding (UTF-8 or UTF-16, from a byte-order mark or the
        # XML declaration) and fails at once on anything that isn't XML, a PDF included.
        with path.open("rb") as file:
            return _xml_root(file) == _ACSM_ROOT
    except (OSError, ValueError, zipfile.BadZipFile):
        return False


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
