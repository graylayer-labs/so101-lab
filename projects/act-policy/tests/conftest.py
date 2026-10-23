"""Fixtures for act-policy tests: no test may reach the network."""

import socket

import pytest


class NetworkUsed(AssertionError):
    pass


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail any test that opens a network connection (the Hub, say)."""

    def refuse(*args: object, **kwargs: object) -> None:
        raise NetworkUsed("a test tried to open a network connection")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
