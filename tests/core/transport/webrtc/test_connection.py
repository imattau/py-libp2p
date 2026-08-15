import pytest

from libp2p.transport.webrtc.connection import WebRTCConnection
from libp2p.transport.webrtc.framing import WebRTCFrame, encode_frame


class FakeChannel:
    def __init__(self) -> None:
        self.sent: list[bytes] = []
        self.closed = False
        self.readyState = "open"

    def send(self, data: bytes) -> None:
        self.sent.append(data)

    def close(self) -> None:
        self.closed = True

    def on(self, event: str, handler: object) -> None:
        pass


@pytest.mark.trio
async def test_connection_adapts_data_channel_messages() -> None:
    channel = FakeChannel()

    async def engine_call(operation, *args):
        return operation(*args)

    connection = WebRTCConnection(channel, engine_call, is_initiator=True)
    await connection.write(b"hello")
    await connection.feed_message(encode_frame(WebRTCFrame(b"world")))

    assert await connection.read() == b"world"
    assert channel.sent

    await connection.close()
    assert channel.closed


@pytest.mark.trio
async def test_connection_wait_ready_and_remote_close() -> None:
    channel = FakeChannel()

    async def engine_call(operation, *args):
        return operation(*args)

    connection = WebRTCConnection(channel, engine_call, is_initiator=False)
    await connection.wait_ready()
    await connection._finish_remote_close()

    assert await connection.read() == b""
