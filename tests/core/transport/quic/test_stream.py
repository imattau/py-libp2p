import pytest
import trio

from libp2p.stream_muxer.exceptions import (
    MuxedStreamClosed,
    MuxedStreamReset,
)
from libp2p.transport.quic.stream import QuicStream


class FakeConnection:
    def __init__(self):
        self.sent = []
        self.resets = []

    def send_stream_data(self, stream_id, data, end_stream=False):
        self.sent.append((stream_id, data, end_stream))

    def reset_stream(self, stream_id, error_code=0):
        self.resets.append((stream_id, error_code))


class FakeMuxedConnection:
    pass


@pytest.mark.trio
async def test_quic_stream_reads_fin_and_writes_directly():
    connection = FakeConnection()
    flushes = 0

    async def flush():
        nonlocal flushes
        flushes += 1

    stream = QuicStream(3, FakeMuxedConnection(), connection, flush)
    stream.feed_data(b"hello", False)
    stream.feed_data(b" world", True)

    assert await stream.read(5) == b"hello"
    assert await stream.read() == b" world"
    with pytest.raises(EOFError):
        await stream.read()

    await stream.write(b"reply")
    await stream.close()
    assert connection.sent == [
        (3, b"reply", False),
        (3, b"", True),
    ]
    assert flushes == 2


@pytest.mark.trio
async def test_quic_stream_reset_wakes_reader_and_rejects_writes():
    connection = FakeConnection()
    stream = QuicStream(9, FakeMuxedConnection(), connection, lambda: trio.sleep(0))
    reader_done = trio.Event()

    async with trio.open_nursery() as nursery:
        result = []

        async def read_stream():
            with pytest.raises(MuxedStreamReset) as error:
                await stream.read()
            result.append(error.value)
            reader_done.set()

        nursery.start_soon(read_stream)
        await trio.sleep(0)
        await stream.reset()
        await reader_done.wait()
        nursery.cancel_scope.cancel()

    assert connection.resets == [(9, 0)]
    assert result and isinstance(result[0], MuxedStreamReset)
    with pytest.raises(MuxedStreamClosed):
        await stream.write(b"after reset")
