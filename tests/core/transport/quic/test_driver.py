from dataclasses import dataclass

import pytest
import trio

from libp2p.transport.quic.config import QuicTransportConfig
from libp2p.transport.quic.driver import QuicTrioDriver


@dataclass
class FakeBackend:
    datagrams: list[tuple[bytes, tuple[str, int]]]
    events: list[str]
    timer: float | None = None
    received: list[tuple[bytes, tuple[str, int], float]] | None = None
    timers_handled: int = 0

    def __post_init__(self):
        self.received = []

    def datagrams_to_send(self, now):
        datagrams, self.datagrams = self.datagrams, []
        return datagrams

    def get_timer(self):
        return self.timer

    def handle_timer(self, now):
        self.timers_handled += 1
        self.timer = None

    def next_event(self):
        return self.events.pop(0) if self.events else None

    def receive_datagram(self, data, addr, now):
        self.received.append((data, addr, now))


@dataclass
class FakeSocket:
    incoming: list[tuple[bytes, tuple[str, int]]]
    sent: list[tuple[bytes, tuple[str, int]]] | None = None
    block_empty_once: bool = False

    def __post_init__(self):
        self.sent = []

    async def recvfrom(self, max_bytes):
        if not self.incoming:
            if self.block_empty_once:
                self.block_empty_once = False
                await trio.sleep_forever()
            raise trio.EndOfChannel
        return self.incoming.pop(0)

    async def sendto(self, data, addr):
        self.sent.append((data, addr))


@pytest.mark.trio
async def test_driver_routes_datagrams_events_and_output():
    backend = FakeBackend(
        [(b"response", ("127.0.0.1", 2))],
        ["connected"],
    )
    socket = FakeSocket([(b"request", ("127.0.0.1", 1))])
    events = []

    with pytest.raises(trio.EndOfChannel):
        await QuicTrioDriver(
            backend,
            socket,
            events.append,
            QuicTransportConfig(max_datagram_size=1400),
        ).run()

    assert events == ["connected"]
    assert backend.received[0][0:2] == (b"request", ("127.0.0.1", 1))
    assert socket.sent == [(b"response", ("127.0.0.1", 2))]


@pytest.mark.trio
async def test_driver_processes_backend_timer():
    backend = FakeBackend([], [], timer=0.0)
    socket = FakeSocket([], block_empty_once=True)
    driver = QuicTrioDriver(backend, socket, lambda event: None)

    with pytest.raises(trio.EndOfChannel):
        await driver.run()

    assert backend.timers_handled == 1
