import pytest

from libp2p.transport.quic.events import (
    QuicHandshakeComplete,
    QuicStreamData,
)
from libp2p.transport.quic.stream_manager import QuicStreamManager


class FakeConnection:
    def __init__(self):
        self.next_stream_id = 0
        self.sent = []

    def get_next_available_stream_id(self, is_unidirectional=False):
        assert not is_unidirectional
        stream_id = self.next_stream_id
        self.next_stream_id += 4
        return stream_id

    def send_stream_data(self, stream_id, data, end_stream=False):
        self.sent.append((stream_id, data, end_stream))

    def reset_stream(self, stream_id, error_code=0):
        pass


@pytest.mark.trio
async def test_manager_opens_and_routes_native_streams():
    connection = FakeConnection()
    incoming = []
    manager = QuicStreamManager(
        connection,
        object(),
        lambda: _completed(),
        incoming.append,
    )

    outbound = await manager.open_stream()
    assert outbound.stream_id == 0
    assert manager.streams[0] is outbound

    assert manager.handle_event(QuicStreamData(4, b"hello", True))
    assert manager.handle_event(QuicStreamData(4, b"ignored", False))
    assert len(incoming) == 1
    assert await incoming[0].read() == b"hello"
    assert incoming[0] is manager.streams[4]


@pytest.mark.trio
async def test_manager_tracks_handshake_and_ignores_unknown_events():
    manager = QuicStreamManager(FakeConnection(), object(), _completed)
    handshake = QuicHandshakeComplete("libp2p", False, True)

    assert manager.handle_event(handshake)
    assert manager.handshake == handshake
    assert not manager.handle_event(object())


async def _completed():
    return None
