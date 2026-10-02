"""Tests must never touch live courier sites. Any non-loopback connect fails loudly.

Loopback stays allowed because asyncio on Windows uses a localhost socketpair internally.
"""

import socket

import pytest

LOOPBACK = {"127.0.0.1", "::1", "localhost"}


class LiveNetworkBlocked(RuntimeError):
    pass


def _host_of(address) -> str | None:
    if isinstance(address, tuple) and address:
        return str(address[0])
    return None  # AF_UNIX path etc.


def _refuse(address):
    raise LiveNetworkBlocked(
        f"Tests are offline-only (tried to reach {address!r}). Use fixtures / httpx.MockTransport. "
        "Only `python -m courier_tracking.drift --live` may call live sites."
    )


@pytest.fixture(autouse=True)
def _block_network(monkeypatch):
    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex

    def connect(self, address):
        host = _host_of(address)
        if host is not None and host not in LOOPBACK:
            _refuse(address)
        return real_connect(self, address)

    def connect_ex(self, address):
        host = _host_of(address)
        if host is not None and host not in LOOPBACK:
            _refuse(address)
        return real_connect_ex(self, address)

    real_create_connection = socket.create_connection

    def create_connection(address, *args, **kwargs):
        if _host_of(address) not in LOOPBACK:
            _refuse(address)
        return real_create_connection(address, *args, **kwargs)

    monkeypatch.setattr(socket.socket, "connect", connect)
    monkeypatch.setattr(socket.socket, "connect_ex", connect_ex)
    monkeypatch.setattr(socket, "create_connection", create_connection)
