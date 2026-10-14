"""The test suite runs with outbound network blocked (MAIN-R2, MAIN-AC1).

192.0.2.1 is TEST-NET-1 (RFC 5737) and `.invalid` names never resolve (RFC 6761), so only
the suite's guard can explain an immediate "blocked" error instead of a timeout or OSError.
"""

import socket

import pytest

BLOCKED = "outbound network access is blocked"


@pytest.mark.ac("MAIN-AC1")
def test_outbound_tcp_connect_is_blocked() -> None:
    with pytest.raises(RuntimeError, match=BLOCKED):
        socket.create_connection(("192.0.2.1", 80), timeout=2)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        with pytest.raises(RuntimeError, match=BLOCKED):
            sock.connect_ex(("192.0.2.1", 80))
        with pytest.raises(RuntimeError, match=BLOCKED):
            sock.connect(("pdf2epub-test.invalid", 80))


@pytest.mark.ac("MAIN-AC1")
def test_outbound_udp_send_is_blocked() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        with pytest.raises(RuntimeError, match=BLOCKED):
            sock.sendto(b"x", ("192.0.2.1", 53))
        with pytest.raises(RuntimeError, match=BLOCKED):
            sock.sendto(b"x", 0, ("192.0.2.1", 53))
        with pytest.raises(RuntimeError, match=BLOCKED):
            sock.sendmsg([b"x"], [], 0, ("192.0.2.1", 53))


@pytest.mark.ac("MAIN-AC1")
def test_outbound_name_lookups_are_blocked() -> None:
    for lookup in (
        lambda: socket.getaddrinfo("pdf2epub-test.invalid", 80),
        lambda: socket.gethostbyname("pdf2epub-test.invalid"),
        lambda: socket.gethostbyname_ex("pdf2epub-test.invalid"),
        lambda: socket.gethostbyaddr("192.0.2.1"),
        lambda: socket.getnameinfo(("192.0.2.1", 53), socket.NI_NAMEREQD),
    ):
        with pytest.raises(RuntimeError, match=BLOCKED):
            lookup()


@pytest.mark.ac("MAIN-AC1")
def test_loopback_stays_available_for_test_servers() -> None:
    # coding.md section 6 allows a loopback server started by the test itself.
    with socket.create_server(("127.0.0.1", 0)) as server:
        port = server.getsockname()[1]
        with socket.create_connection(("localhost", port), timeout=2) as client:
            conn, _ = server.accept()
            with conn:
                client.sendall(b"ping")
                assert conn.recv(4) == b"ping"
    with (
        socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as rx,
        socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as tx,
    ):
        rx.bind(("127.0.0.1", 0))
        tx.sendto(b"pong", rx.getsockname())
        assert rx.recv(4) == b"pong"
