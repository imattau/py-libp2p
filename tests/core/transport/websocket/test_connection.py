import pytest

from libp2p.transport.websocket.connection import WebSocketConnection


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
