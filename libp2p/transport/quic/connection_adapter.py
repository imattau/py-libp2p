from typing import Any

import trio

from .config import QuicTransportConfig
from .driver import (
    QuicDatagramSocket,
    QuicTrioDriver,
)
from .stream import QuicStream
from .stream_manager import QuicStreamManager


class QuicConnectionAdapter:
    """Connect the Trio driver, stream manager, and native QUIC backend."""

    def __init__(self, connection: Any, muxed_conn: object) -> None:
        self.connection = connection
        self.muxed_conn = muxed_conn
        self._incoming_send, self._incoming_receive = trio.open_memory_channel(100)
        self._driver: QuicTrioDriver | None = None
        self._manager = QuicStreamManager(
            connection,
            muxed_conn,
            self._flush_output,
            self._queue_incoming_stream,
        )

    async def run(
        self,
        socket: QuicDatagramSocket,
        config: QuicTransportConfig | None = None,
    ) -> None:
        self._driver = QuicTrioDriver(
            self.connection,
            socket,
            self._handle_event,
            config,
        )
        await self._driver.run()

    async def open_stream(self) -> QuicStream:
        return await self._manager.open_stream()

    async def accept_stream(self) -> QuicStream:
        return await self._incoming_receive.receive()

    def _handle_event(self, event: object) -> None:
        self._manager.handle_event(event)

    def _queue_incoming_stream(self, stream: QuicStream) -> None:
        try:
            self._incoming_send.send_nowait(stream)
        except trio.WouldBlock as error:
            raise RuntimeError("too many pending incoming QUIC streams") from error

    async def _flush_output(self) -> None:
        if self._driver is None:
            raise RuntimeError("QUIC connection is not running")
        await self._driver._process_backend()
