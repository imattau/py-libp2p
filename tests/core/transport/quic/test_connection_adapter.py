import pytest

from libp2p.transport.quic.connection_adapter import QuicConnectionAdapter
from libp2p.transport.quic.events import QuicStreamData


class FakeConnection:
    def get_next_available_stream_id(self, is_unidirectional=False):
        return 0

    def send_stream_data(self, stream_id, data, end_stream=False):
        pass

    def reset_stream(self, stream_id, error_code=0):
        pass


@pytest.mark.trio
async def test_connection_adapter_opens_and_accepts_streams():
    adapter = QuicConnectionAdapter(FakeConnection(), object())

    outbound = await adapter.open_stream()
    adapter._handle_event(QuicStreamData(4, b"incoming", True))
    inbound = await adapter.accept_stream()

    assert outbound.stream_id == 0
    assert inbound.stream_id == 4
    assert await inbound.read() == b"incoming"


@pytest.mark.trio
async def test_stream_write_requires_running_connection():
    adapter = QuicConnectionAdapter(FakeConnection(), object())
    stream = await adapter.open_stream()

    with pytest.raises(RuntimeError, match="not running"):
        await stream.write(b"data")
