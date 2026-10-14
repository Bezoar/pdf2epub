"""The test suite runs with outbound network blocked (MAIN-R2, MAIN-AC1)."""

import socket

import pytest
from pytest_socket import SocketConnectBlockedError


@pytest.mark.ac("MAIN-AC1")
def test_outbound_connections_are_blocked_during_the_suite() -> None:
    # 192.0.2.1 is TEST-NET-1 (RFC 5737): never routed, so only the block can explain
    # an immediate SocketConnectBlockedError instead of a timeout or OSError.
    with pytest.raises(SocketConnectBlockedError):
        socket.create_connection(("192.0.2.1", 80), timeout=2)


@pytest.mark.ac("MAIN-AC1")
def test_loopback_stays_available_for_test_servers() -> None:
    # coding.md section 6 allows a loopback server started by the test itself.
    with socket.create_server(("127.0.0.1", 0)) as server:
        port = server.getsockname()[1]
        with socket.create_connection(("127.0.0.1", port), timeout=2):
            conn, _ = server.accept()
            conn.close()
