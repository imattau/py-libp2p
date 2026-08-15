from collections.abc import Awaitable, Callable
from typing import Protocol

from .events import (
    QuicConnectionClosed,
    QuicHandshakeComplete,
    QuicStreamData,
)
from .stream import (
    QuicStream,
    QuicStreamConnection,
)


class QuicMuxedConnection(Protocol):
    def get_next_available_stream_id(self, is_unidirectional: bool = False) -> int: ...


class QuicManagedConnection(QuicMuxedConnection, QuicStreamConnection, Protocol):
    pass


class QuicStreamManager:
    """Own native QUIC streams and route normalized transport events."""

    def __init__(
        self,
        connection: QuicManagedConnection,
        muxed_conn: object,
        flush_output: Callable[[], Awaitable[None]],
        on_incoming_stream: Callable[[QuicStream], None] | None = None,
    ) -> None:
        self.connection = connection
        self.muxed_conn = muxed_conn
        self.flush_output = flush_output
        self.on_incoming_stream = on_incoming_stream
        self.streams: dict[int, QuicStream] = {}
        self.handshake: QuicHandshakeComplete | None = None
        self.closed: QuicConnectionClosed | None = None

    async def open_stream(self) -> QuicStream:
        stream_id = self.connection.get_next_available_stream_id(
            is_unidirectional=False
        )
        return self._get_or_create(stream_id)

    def handle_event(self, event: object) -> bool:
        if isinstance(event, QuicHandshakeComplete):
            self.handshake = event
            return True
        if isinstance(event, QuicConnectionClosed):
            self.closed = event
            return True
        if isinstance(event, QuicStreamData):
            stream = self._get_or_create(event.stream_id, incoming=True)
            stream.feed_data(event.data, event.end_stream)
            return True
        return False

    def _get_or_create(self, stream_id: int, incoming: bool = False) -> QuicStream:
        stream = self.streams.get(stream_id)
        if stream is None:
            stream = QuicStream(
                stream_id,
                self.muxed_conn,
                self.connection,
                self.flush_output,
            )
            self.streams[stream_id] = stream
            if incoming and self.on_incoming_stream is not None:
                self.on_incoming_stream(stream)
        return stream
