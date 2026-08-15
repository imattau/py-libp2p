from collections import deque
from collections.abc import Awaitable, Callable
from typing import Protocol

import trio

from libp2p.abc import (
    IMuxedConn,
    IMuxedStream,
)
from libp2p.stream_muxer.exceptions import (
    MuxedStreamClosed,
    MuxedStreamEOF,
    MuxedStreamReset,
)


class QuicStreamConnection(Protocol):
    def send_stream_data(
        self, stream_id: int, data: bytes, end_stream: bool = False
    ) -> None: ...

    def reset_stream(self, stream_id: int, error_code: int = 0) -> None: ...


class QuicStream(IMuxedStream):
    """Adapt one native QUIC bidirectional stream to ``IMuxedStream``."""

    def __init__(
        self,
        stream_id: int,
        muxed_conn: IMuxedConn,
        connection: QuicStreamConnection,
        flush_output: Callable[[], Awaitable[None]],
        is_initiator: bool = True,
    ) -> None:
        self.stream_id = stream_id
        self.muxed_conn = muxed_conn
        self._connection = connection
        self._flush_output = flush_output
        self.is_initiator = is_initiator
        self._buffer: deque[bytes] = deque()
        self._read_event = trio.Event()
        self._read_closed = False
        self._write_closed = False
        self._reset = False

    def feed_data(self, data: bytes, end_stream: bool) -> None:
        """Deliver a normalized QUIC stream event to this stream."""
        if self._reset or self._read_closed:
            return
        if data:
            self._buffer.append(data)
        if end_stream:
            self._read_closed = True
        self._read_event.set()

    async def read(self, n: int | None = None) -> bytes:
        if self._reset:
            raise MuxedStreamReset()
        while True:
            if self._buffer:
                data = self._buffer.popleft()
                if n is not None and len(data) > n:
                    self._buffer.appendleft(data[n:])
                    return data[:n]
                return data
            if self._read_closed:
                raise MuxedStreamEOF()
            event = self._read_event
            await event.wait()
            if self._reset:
                raise MuxedStreamReset()
            if event is self._read_event:
                self._read_event = trio.Event()

    async def write(self, data: bytes) -> None:
        if self._reset or self._write_closed:
            raise MuxedStreamClosed()
        self._connection.send_stream_data(self.stream_id, data)
        await self._flush_output()

    async def close(self) -> None:
        if self._reset or self._write_closed:
            return
        self._connection.send_stream_data(self.stream_id, b"", end_stream=True)
        self._write_closed = True
        await self._flush_output()

    async def reset(self) -> None:
        if self._reset:
            return
        self._connection.reset_stream(self.stream_id)
        self._reset = True
        self._read_event.set()
        await self._flush_output()

    def set_deadline(self, ttl: int) -> bool:
        return False

    def get_remote_address(self) -> tuple[str, int] | None:
        return None

    async def __aenter__(self) -> "QuicStream":
        return self
