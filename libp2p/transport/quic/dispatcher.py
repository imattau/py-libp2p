from collections.abc import Callable
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

    def __init__(self, socket: Any) -> None:
        self.socket = socket
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
        if route is None:
            return False

        connection, handle_event = route
        timestamp = trio.current_time() if now is None else now
        connection.receive_datagram(data, addr, timestamp)
        drain_events(
            connection,
            lambda event: handle_event(normalize_event(event)),
        )
        await flush_datagrams(connection, self.socket.sendto, timestamp)
        return True
