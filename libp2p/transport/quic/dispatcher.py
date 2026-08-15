from collections.abc import Awaitable, Callable
from typing import Any

import trio

from .backend import (
    QuicConnectionBackend,
    drain_events,
    flush_datagrams,
)
from .events import normalize_event


class QuicDatagramDispatcher:
    """Route UDP datagrams to QUIC connections sharing one socket."""

    def __init__(
        self,
        socket: Any,
        on_unknown: Callable[
            [Any, bytes],
            Awaitable[tuple[QuicConnectionBackend, Callable[[Any], None]] | None],
        ]
        | None = None,
    ) -> None:
        self.socket = socket
        self.on_unknown = on_unknown
        self._routes: dict[
            Any, tuple[QuicConnectionBackend, Callable[[Any], None]]
        ] = {}

    def register(
        self,
        addr: Any,
        connection: QuicConnectionBackend,
        handle_event: Callable[[Any], None],
    ) -> None:
        if addr in self._routes:
            raise ValueError(f"a QUIC connection is already registered for {addr!r}")
        self._routes[addr] = (connection, handle_event)

    def unregister(self, addr: Any) -> None:
        self._routes.pop(addr, None)

    async def run(self, max_datagram_size: int = 1200) -> None:
        """Own the shared socket receive loop until cancelled or closed."""
        while True:
            data, addr = await self.socket.recvfrom(max_datagram_size)
            await self.handle_datagram(data, addr)

    async def handle_datagram(
        self, data: bytes, addr: Any, now: float | None = None
    ) -> bool:
        route = self._routes.get(addr)
        if route is None and self.on_unknown is not None:
            route = await self.on_unknown(addr, data)
            if route is not None:
                self._routes[addr] = route
        if route is None:
            return False

        connection, handle_event = route
        timestamp = trio.current_time() if now is None else now
        connection.receive_datagram(data, addr, timestamp)
        drain_events(
            connection,
            lambda event: handle_event(normalize_event(event)),
        )
        await self.flush_connection(addr, timestamp)
        return True

    async def flush_connection(self, addr: Any, now: float | None = None) -> int:
        route = self._routes.get(addr)
        if route is None:
            return 0
        timestamp = trio.current_time() if now is None else now
        return await flush_datagrams(route[0], self.socket.sendto, timestamp)
