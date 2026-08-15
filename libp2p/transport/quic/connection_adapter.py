from collections.abc import Awaitable, Callable
from typing import Any

import trio

from libp2p.peer.id import ID
from libp2p.stream_muxer.exceptions import MuxedConnUnavailable

from .config import QuicTransportConfig
from .connection import peer_id_from_certificate
from .driver import (
    QuicDatagramSocket,
    QuicTrioDriver,
)
from .events import (
    QuicConnectionClosed,
    QuicHandshakeComplete,
)
from .stream import QuicStream
from .stream_manager import QuicStreamManager


class QuicConnectionAdapter:
    """Connect the Trio driver, stream manager, and native QUIC backend."""

    def __init__(
        self,
        connection: Any,
        muxed_conn: object,
        flush_output: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        self.connection = connection
        self.muxed_conn = muxed_conn
        self._external_flush_output = flush_output
        self._incoming_send, self._incoming_receive = trio.open_memory_channel(100)
        self._driver: QuicTrioDriver | None = None
        self._run_scope: trio.CancelScope | None = None
        self._socket: QuicDatagramSocket | None = None
        self._handshake_complete = trio.Event()
        self._closed = trio.Event()
        self.event_started = trio.Event()
        self.remote_peer_id: ID | None = None
        self.on_close: Callable[[], Awaitable[None]] | None = None
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
        self._socket = socket
        self._run_scope = trio.CancelScope()
        self._driver = QuicTrioDriver(
            self.connection,
            socket,
            self._handle_event,
            config,
        )
        with self._run_scope:
            await self._driver.run()

    async def open_stream(self) -> QuicStream:
        return await self._manager.open_stream()

    async def accept_stream(self) -> QuicStream:
        stream = await self._incoming_receive.receive()
        if stream is None:
            raise MuxedConnUnavailable("QUIC connection closed")
        return stream

    async def wait_handshake(self) -> None:
        await self._handshake_complete.wait()

    async def start(self) -> None:
        """Mark a dispatcher-owned connection ready for swarm monitoring."""
        self.event_started.set()

    @property
    def peer_id(self) -> ID:
        if self.remote_peer_id is None:
            raise RuntimeError("QUIC handshake has not completed")
        return self.remote_peer_id

    @property
    def is_closed(self) -> bool:
        return self._closed.is_set()

    async def close(self) -> None:
        if self._run_scope is not None:
            self._run_scope.cancel()
        if self._socket is not None:
            await self._socket.aclose()
        self._closed.set()
        if self.on_close is not None:
            await self.on_close()

    def _handle_event(self, event: object) -> None:
        self._manager.handle_event(event)
        if isinstance(event, QuicHandshakeComplete):
            certificate = getattr(self.connection, "tls", None)
            certificate = getattr(certificate, "_peer_certificate", None)
            if certificate is None:
                raise ValueError("QUIC handshake did not provide a peer certificate")
            self.remote_peer_id = peer_id_from_certificate(certificate)
            self._handshake_complete.set()
        elif isinstance(event, QuicConnectionClosed):
            self._closed.set()
            try:
                self._incoming_send.send_nowait(None)
            except trio.WouldBlock:
                pass

    def _queue_incoming_stream(self, stream: QuicStream) -> None:
        try:
            self._incoming_send.send_nowait(stream)
        except trio.WouldBlock as error:
            raise RuntimeError("too many pending incoming QUIC streams") from error

    async def _flush_output(self) -> None:
        if self._external_flush_output is not None:
            await self._external_flush_output()
            return
        if self._driver is None:
            raise RuntimeError("QUIC connection is not running")
        await self._driver._process_backend()
