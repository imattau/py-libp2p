import pytest

from libp2p.transport.quic.dispatcher import QuicDatagramDispatcher
from libp2p.transport.quic.events import QuicConnectionClosed, QuicStreamData


class FakeConnection:
    def __init__(self, host_cid=None):
        self.host_cid = host_cid
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


def test_dispatcher_removes_secondary_cid_route_without_dropping_primary():
    dispatcher = QuicDatagramDispatcher(FakeSocket())
    address = ("127.0.0.1", 4)
    primary = FakeConnection(b"primary")
    secondary = FakeConnection(b"secondary")

    dispatcher.register(address, primary, lambda event: None)
    dispatcher.register(address, secondary, lambda event: None)
    dispatcher.unregister(address, secondary)

    assert dispatcher._routes[address][0] is primary
    assert (address, b"secondary") not in dispatcher._cid_routes

    dispatcher.unregister(address, primary)
    assert address not in dispatcher._routes


class FakeSocket:
    def __init__(self):
        self.sent = []
        self.incoming = []

    async def recvfrom(self, max_bytes):
        if not self.incoming:
            raise RuntimeError("socket closed")
        return self.incoming.pop(0)

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


@pytest.mark.trio
async def test_dispatcher_drops_malformed_unknown_packets():
    dispatcher = QuicDatagramDispatcher(FakeSocket())

    async def reject(_addr, _data):
        raise ValueError("malformed QUIC header")

    dispatcher.on_unknown = reject
    assert not await dispatcher.handle_datagram(b"packet", ("127.0.0.1", 9))


@pytest.mark.trio
async def test_dispatcher_unregisters_closed_connections():
    dispatcher = QuicDatagramDispatcher(FakeSocket())
    connection = FakeConnection()
    connection.events = [QuicConnectionClosed(1, None, "closed")]
    dispatcher.register(("127.0.0.1", 4), connection, lambda event: None)

    assert await dispatcher.handle_datagram(b"packet", ("127.0.0.1", 4))
    assert ("127.0.0.1", 4) not in dispatcher._routes


@pytest.mark.trio
async def test_dispatcher_run_owns_socket_receive_loop():
    socket = FakeSocket()
    socket.incoming.append((b"packet", ("127.0.0.1", 4)))
    dispatcher = QuicDatagramDispatcher(socket)
    connection = FakeConnection()
    dispatcher.register(("127.0.0.1", 4), connection, lambda event: None)

    with pytest.raises(RuntimeError, match="socket closed"):
        await dispatcher.run(max_datagram_size=1400)

    assert connection.received[0][0] == b"packet"
