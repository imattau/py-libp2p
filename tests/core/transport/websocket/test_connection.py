import pytest
from multiaddr import Multiaddr
import trio

from libp2p.transport.exceptions import OpenConnectionError
from libp2p.transport.websocket.connection import WebSocketConnection
from libp2p.transport.websocket.transport import WebSocket, WebSocketListener


class FakeWebSocket:
    def __init__(self, messages):
        self.messages = list(messages)
        self.sent = []
        self.closed = False

    async def get_message(self):
        return self.messages.pop(0)

    async def send_message(self, message):
        self.sent.append(message)

    async def aclose(self):
        self.closed = True


@pytest.mark.trio
async def test_websocket_connection_adapts_binary_messages_to_stream():
    websocket = FakeWebSocket([b"hello", b" world"])
    connection = WebSocketConnection(websocket, True)

    assert await connection.read(2) == b"he"
    assert await connection.read() == b"llo"
    await connection.write(b"reply")
    assert websocket.sent == [b"reply"]
    assert connection.is_initiator
    await connection.close()
    assert websocket.closed


@pytest.mark.trio
async def test_websocket_connection_rejects_text_messages():
    connection = WebSocketConnection(FakeWebSocket(["text"]), False)

    with pytest.raises(ValueError, match="binary"):
        await connection.read()


@pytest.mark.trio
async def test_websocket_transport_round_trip_over_loopback():
    received = trio.Event()

    async def handle_server_connection(connection):
        assert await connection.read() == b"request"
        await connection.write(b"response")
        received.set()
        await connection.close()

    listener = WebSocketListener(handle_server_connection)
    transport = WebSocket()
    async with trio.open_nursery() as nursery:
        assert await listener.listen(
            Multiaddr("/ip4/127.0.0.1/tcp/0/ws"), nursery
        )
        connection = await transport.dial(listener.get_addrs()[0])
        await connection.write(b"request")
        assert await connection.read() == b"response"
        await received.wait()
        await connection.close()
        nursery.cancel_scope.cancel()
    await listener.close()


@pytest.mark.trio
async def test_wss_requires_explicit_tls_configuration():
    address = Multiaddr("/ip4/127.0.0.1/tcp/443/wss")
    transport = WebSocket()

    with pytest.raises(OpenConnectionError, match="SSL context"):
        await transport.dial(address)
