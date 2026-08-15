from dataclasses import dataclass

import pytest

from libp2p.transport.quic.backend import (
    drain_events,
    flush_datagrams,
)


@dataclass
class FakeBackend:
    datagrams: list[tuple[bytes, tuple[str, int]]]
    events: list[str]

    def datagrams_to_send(self, now):
        return self.datagrams

    def get_timer(self):
        return None

    def handle_timer(self, now):
        pass

    def next_event(self):
        return self.events.pop(0) if self.events else None

    def receive_datagram(self, data, addr, now):
        pass


@pytest.mark.trio
async def test_flush_datagrams_uses_backend_addresses():
    backend = FakeBackend(
        [(b"one", ("127.0.0.1", 1)), (b"two", ("127.0.0.1", 2))], []
    )
    sent = []

    count = await flush_datagrams(
        backend, lambda data, addr: sent.append((data, addr)), 1.0
    )

    assert count == 2
    assert sent == backend.datagrams


def test_drain_events_delivers_until_backend_is_empty():
    backend = FakeBackend([], ["first", "second"])
    events = []

    count = drain_events(backend, events.append)

    assert count == 2
    assert events == ["first", "second"]
