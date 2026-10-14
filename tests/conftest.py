"""Suite-wide test policy from coding.md section 6.

- Outbound network access is blocked for the whole run (MAIN-R2, MAIN-AC1): TCP connects,
  UDP sends and name lookups to anything but loopback raise ``RuntimeError``. A loopback
  server started by the test itself stays usable. Unix-domain sockets are untouched.
- Tests marked ``tesseract`` skip when Tesseract is missing, except where
  ``PDF2EPUB_REQUIRE_TESSERACT=1`` (the CI coverage job), where they fail instead.
- Every EPUB a test writes under its ``tmp_path`` is checked with epubcheck when the test
  ends, and any epubcheck error fails it (TST-R19).

- Every event a ``RecordingSink`` receives, and every event or report a test passes to
  ``validate_event``, is checked against the JSON Schema shipped in the package; an
  invalid one fails the test, naming the event type and the offending field (TST-R18).

It also holds what the seams share: copies of the committed fixtures, a recording event
sink, the schema check, the epubcheck step, and an in-process conversion helper.
"""

import ipaddress
import json
import os
import shutil
import socket
import subprocess
import threading
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from functools import cache
from importlib import resources
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

BLOCKED = "outbound network access is blocked in the test suite"
LOOPBACK_NAMES = {"localhost", "localhost.localdomain", "ip6-localhost", ""}

# Set in the CI coverage job, where a skipped `tesseract` test must fail the job.
REQUIRE_TESSERACT = "PDF2EPUB_REQUIRE_TESSERACT"


def _is_loopback(host: object) -> bool:
    if host is None:
        return True
    if isinstance(host, bytes):
        host = host.decode("ascii", "replace")
    if not isinstance(host, str):
        return False
    name = host.split("%", 1)[0].strip("[]").lower()
    if name in LOOPBACK_NAMES:
        return True
    try:
        address = ipaddress.ip_address(name)
    except ValueError:
        return False
    # An IPv4-mapped IPv6 address (::ffff:127.0.0.1) reaches the IPv4 loopback.
    mapped = getattr(address, "ipv4_mapped", None)
    return address.is_loopback or (mapped is not None and mapped.is_loopback)


def _check_address(sock: socket.socket, address: Any) -> None:
    if sock.family in (socket.AF_INET, socket.AF_INET6) and not _is_loopback(address[0]):
        raise RuntimeError(f"{BLOCKED}: {address!r}")


def _install_network_guard() -> None:
    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex
    real_sendto = socket.socket.sendto
    real_sendmsg = socket.socket.sendmsg
    real_getaddrinfo = socket.getaddrinfo
    real_gethostbyname = socket.gethostbyname
    real_gethostbyname_ex = socket.gethostbyname_ex
    real_gethostbyaddr = socket.gethostbyaddr
    real_getnameinfo = socket.getnameinfo

    def connect(self: socket.socket, address: Any) -> None:
        _check_address(self, address)
        real_connect(self, address)

    def connect_ex(self: socket.socket, address: Any) -> int:
        _check_address(self, address)
        return real_connect_ex(self, address)

    def sendto(self: socket.socket, data: Any, *args: Any) -> int:
        _check_address(self, args[-1])
        return real_sendto(self, data, *args)

    def sendmsg(self: socket.socket, buffers: Any, *args: Any, **kwargs: Any) -> int:
        address = args[2] if len(args) > 2 else kwargs.get("address")
        if address is not None:
            _check_address(self, address)
        return real_sendmsg(self, buffers, *args, **kwargs)

    def getaddrinfo(host: Any, *args: Any, **kwargs: Any) -> Any:
        if not _is_loopback(host):
            raise RuntimeError(f"{BLOCKED}: name lookup of {host!r}")
        return real_getaddrinfo(host, *args, **kwargs)

    def gethostbyname(host: str) -> str:
        if not _is_loopback(host):
            raise RuntimeError(f"{BLOCKED}: name lookup of {host!r}")
        return real_gethostbyname(host)

    def gethostbyname_ex(host: str) -> tuple[str, list[str], list[str]]:
        if not _is_loopback(host):
            raise RuntimeError(f"{BLOCKED}: name lookup of {host!r}")
        return real_gethostbyname_ex(host)

    def gethostbyaddr(host: str) -> tuple[str, list[str], list[str]]:
        if not _is_loopback(host):
            raise RuntimeError(f"{BLOCKED}: address lookup of {host!r}")
        return real_gethostbyaddr(host)

    def getnameinfo(sockaddr: Any, flags: int) -> tuple[str, str]:
        if not _is_loopback(sockaddr[0]):
            raise RuntimeError(f"{BLOCKED}: address lookup of {sockaddr!r}")
        return real_getnameinfo(sockaddr, flags)

    for name, func in [
        ("connect", connect),
        ("connect_ex", connect_ex),
        ("sendto", sendto),
        ("sendmsg", sendmsg),
    ]:
        setattr(socket.socket, name, func)
    socket.getaddrinfo = getaddrinfo
    socket.gethostbyname = gethostbyname
    socket.gethostbyname_ex = gethostbyname_ex
    socket.gethostbyaddr = gethostbyaddr
    socket.getnameinfo = getnameinfo


def pytest_configure(config: pytest.Config) -> None:
    _install_network_guard()


def pytest_runtest_setup(item: pytest.Item) -> None:
    if item.get_closest_marker("tesseract") is None or shutil.which("tesseract"):
        return
    if os.environ.get(REQUIRE_TESSERACT) == "1":
        pytest.fail(f"Tesseract is not on PATH, and {REQUIRE_TESSERACT}=1 forbids skipping")
    pytest.skip("Tesseract is not on PATH")


# --- Fixtures shared by the seams ------------------------------------------------------

FIXTURES = Path(__file__).resolve().parent / "fixtures"
NOVEL = FIXTURES / "born-digital" / "novel.pdf"
PUBLIC_DOMAIN_SAMPLE = FIXTURES / "public-domain" / "nasa-sp-4319-premonition.pdf"


@pytest.fixture
def novel_pdf(tmp_path: Path) -> Path:
    """A private copy of the synthetic novel fixture, so its EPUB lands in ``tmp_path``."""
    target = tmp_path / "novel.pdf"
    shutil.copyfile(NOVEL, target)
    return target


@pytest.fixture
def sample_pdf(tmp_path: Path) -> Path:
    """A private copy of the public-domain sample, named ``sample.pdf``."""
    target = tmp_path / "sample.pdf"
    shutil.copyfile(PUBLIC_DOMAIN_SAMPLE, target)
    return target


# --- The event schema (TST-R18) --------------------------------------------------------

# The schema's definition for each known event type, where its name differs from the type.
_DEFINITION = {"issue": "issue_event"}


@cache
def _schema() -> dict[str, Any]:
    """The JSON Schema shipped inside the installed package (API-R26)."""
    packaged = resources.files("pdf2epub") / "schema" / "events.v1.json"
    schema: dict[str, Any] = json.loads(packaged.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return schema


@cache
def _validator(definition: str | None) -> Draft202012Validator:
    """The whole schema; or, for a known type, the envelope plus that type's definition
    alone, whose errors name the offending field rather than "no oneOf branch matched"."""
    schema = _schema()
    if definition is None:
        return Draft202012Validator(schema)
    single = {key: value for key, value in schema.items() if key != "oneOf"}
    single["$ref"] = f"#/$defs/{definition}"
    return Draft202012Validator(single)


def validate_event(event: Any) -> None:
    """Fail the calling test unless ``event`` (an event, or a ``--report`` document)
    validates against the packaged schema. The failure names the event type and each
    offending field."""
    type_ = event.get("type") if isinstance(event, dict) else None
    definition = _DEFINITION.get(type_, type_) if isinstance(type_, str) else None
    if definition not in _schema()["$defs"]:
        definition = None
    errors = list(_validator(definition).iter_errors(event))
    if not errors and definition is not None:
        # The full schema stays the authority; the single-type check only words the error.
        errors = list(_validator(None).iter_errors(event))
    if errors:
        details = "; ".join(
            f"{'/'.join(map(str, e.absolute_path)) or 'top level'}: {e.message}" for e in errors
        )
        pytest.fail(f"invalid {type_!r} event: {details}\n{event!r}", pytrace=False)


@dataclass
class RecordingSink:
    """An event sink that records every event and the thread each one arrived on.

    It validates each event against the packaged schema as it arrives (TST-R18). An
    invalid event fails the test at once: pytest's failure is a ``BaseException``, so the
    core can't mistake it for a conversion error."""

    events: list[dict[str, Any]] = field(default_factory=list)
    threads: set[int] = field(default_factory=set)

    def __call__(self, event: dict[str, Any]) -> None:
        self.threads.add(threading.get_ident())
        validate_event(event)
        self.events.append(event)

    def of_type(self, type_: str) -> list[dict[str, Any]]:
        return [e for e in self.events if e["type"] == type_]


@pytest.fixture
def sink() -> RecordingSink:
    return RecordingSink()


# --- epubcheck (TST-R19) ---------------------------------------------------------------

# Where epubcheck is found: the jar named by EPUBCHECK_JAR (as CI sets it), else an
# `epubcheck` program on PATH. Without either, epubcheck checks skip with a reason
# locally, but fail on CI (where GitHub Actions sets CI=true), so they can't silently
# stop running there.
EPUBCHECK_JAR = "EPUBCHECK_JAR"


def _epubcheck_command() -> list[str] | None:
    jar = os.environ.get(EPUBCHECK_JAR)
    if jar:
        return ["java", "-jar", jar]
    program = shutil.which("epubcheck")
    if program:
        return [program]
    if os.environ.get("CI") == "true":
        pytest.fail(f"epubcheck is not available on CI: set {EPUBCHECK_JAR}")
    return None


# EPUBs that already passed, by (path, size, modification time): each JVM start costs
# seconds, so a file checked by its test isn't checked again at teardown.
_PASSED: set[tuple[str, int, int]] = set()


def run_epubcheck(epub: Path) -> None:
    """Fail the calling test, quoting epubcheck's messages, unless ``epub`` has zero
    epubcheck errors (and zero fatal errors)."""
    command = _epubcheck_command()
    if command is None:
        pytest.skip(f"epubcheck is not available: set {EPUBCHECK_JAR} or put it on PATH")
    stat = epub.stat()
    key = (str(epub.resolve()), stat.st_size, stat.st_mtime_ns)
    if key in _PASSED:
        return
    proc = subprocess.run(
        [*command, "--quiet", str(epub)], capture_output=True, text=True, check=False
    )
    if proc.returncode != 0:
        pytest.fail(f"epubcheck rejected {epub}:\n{proc.stdout}{proc.stderr}", pytrace=False)
    _PASSED.add(key)


@pytest.fixture
def epubcheck() -> Callable[[Path], None]:
    return run_epubcheck


@pytest.fixture(autouse=True)
def _epubcheck_every_written_epub(request: pytest.FixtureRequest) -> Iterator[None]:
    """After each test that used ``tmp_path``, run epubcheck on every EPUB it wrote there
    (TST-R19). Tests that build a deliberately broken EPUB keep it outside ``tmp_path``."""
    if "tmp_path" not in request.fixturenames:
        yield
        return
    # Requested here, during setup, so tmp_path outlives this fixture's teardown.
    tmp_path: Path = request.getfixturevalue("tmp_path")
    yield
    if _epubcheck_command() is None:
        return
    for epub in sorted(tmp_path.rglob("*.epub")):
        run_epubcheck(epub)


def convert_copy(source: Path, target_dir: Path) -> Path:
    """Convert a copy of ``source`` placed in ``target_dir``, in-process through the
    public API, and return the EPUB it wrote. Fails the test unless it converted."""
    from pdf2epub import (
        BatchOptions,
        ConversionOptions,
        DiscoveryOptions,
        InputSpec,
        Outcome,
        plan_batch,
        run_batch,
    )

    pdf = target_dir / source.name
    shutil.copyfile(source, pdf)
    plan = plan_batch([InputSpec(pdf)], DiscoveryOptions())
    report = run_batch(
        plan, BatchOptions(isolation="inprocess"), ConversionOptions(), RecordingSink()
    )
    [result] = report.conversions
    assert result.outcome is Outcome.CONVERTED, result.issues
    assert result.output is not None
    return Path(result.output)
