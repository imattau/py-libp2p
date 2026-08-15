import pytest

from libp2p.transport.quic.dispatcher import QuicDatagramDispatcher
from libp2p.transport.quic.events import QuicStreamData


class FakeConnection:
    def __init__(self):
        self.received = []
        self.events = [QuicStreamData(2, b"reply", True)]
        self.output = [(b"response", ("127.0.0.1", 4))]

    def receive_datagram(self, data, addr, now):
        self.received.append((data, addr, now))

    def next_event(self):
        return self.events.pop(0) if self.events else None

    def datagrams_to_send(self, now):
        output, self.output = self.output, []
        return output


class FakeSocket:
    def __init__(self):
        self.sent = []

    async def sendto(self, data, addr):
        self.sent.append((data, addr))


@pytest.mark.trio
async def test_dispatcher_routes_events_and_flushes_output():
    socket = FakeSocket()
    dispatcher = QuicDatagramDispatcher(socket)
    connection = FakeConnection()
    events = []
    dispatcher.register(("127.0.0.1", 4), connection, events.append)

    assert await dispatcher.handle_datagram(
        b"packet", ("127.0.0.1", 4), now=3.0
    )
    assert connection.received == [(b"packet", ("127.0.0.1", 4), 3.0)]
    assert events == [QuicStreamData(2, b"reply", True)]
    assert socket.sent == [(b"response", ("127.0.0.1", 4))]


@pytest.mark.trio
async def test_dispatcher_ignores_unknown_addresses():
    dispatcher = QuicDatagramDispatcher(FakeSocket())

    assert not await dispatcher.handle_datagram(b"packet", ("127.0.0.1", 9))
