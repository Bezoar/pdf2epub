"""Suite-wide test policy from coding.md section 6.

- Outbound network access is blocked for the whole run (MAIN-R2, MAIN-AC1): TCP connects,
  UDP sends and name lookups to anything but loopback raise ``RuntimeError``. A loopback
  server started by the test itself stays usable. Unix-domain sockets are untouched.
- Tests marked ``tesseract`` skip when Tesseract is missing, except where
  ``PDF2EPUB_REQUIRE_TESSERACT=1`` (the CI coverage job), where they fail instead.
"""

import ipaddress
import os
import shutil
import socket
from typing import Any

import pytest

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
