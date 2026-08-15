import pytest

from libp2p.transport.webrtc.connection import WebRTCConnection
from libp2p.transport.webrtc.framing import WebRTCFrame, encode_frame


class FakeChannel:
    def __init__(self) -> None:
        self.sent: list[bytes] = []
        self.closed = False

    def send(self, data: bytes) -> None:
        self.sent.append(data)

    def close(self) -> None:
        self.closed = True


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
