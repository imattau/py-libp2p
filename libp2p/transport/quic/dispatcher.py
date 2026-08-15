from collections.abc import Awaitable, Callable
from typing import Any

from aioquic.buffer import Buffer
from aioquic.quic.packet import pull_quic_header
import trio

from .backend import (
    QuicConnectionBackend,
    drain_events,
    flush_datagrams,
)
from .events import QuicConnectionClosed, normalize_event


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
        self._cid_routes: dict[
            tuple[Any, bytes], tuple[QuicConnectionBackend, Callable[[Any], None]]
        ] = {}

    def register(
        self,
        addr: Any,
        connection: QuicConnectionBackend,
        handle_event: Callable[[Any], None],
    ) -> None:
        if addr in self._routes:
            route = (connection, handle_event)
            for cid in self._connection_ids(connection):
                self._cid_routes[(addr, cid)] = route
            return
        route = (connection, handle_event)
        self._routes[addr] = route
        for cid in self._connection_ids(connection):
            self._cid_routes[(addr, cid)] = route

    def unregister(
        self, addr: Any, connection: QuicConnectionBackend | None = None
    ) -> None:
        route = self._routes.get(addr)
        if route is None:
            return
        if connection is not None and route[0] is not connection:
            route = next(
                (
                    candidate
                    for (route_addr, _), candidate in self._cid_routes.items()
                    if route_addr == addr and candidate[0] is connection
                ),
                None,
            )
            if route is None:
                return
        for key, candidate in tuple(self._cid_routes.items()):
            if key[0] == addr and candidate is route:
                del self._cid_routes[key]
        if self._routes.get(addr) is route:
            replacement = next(
                (
                    candidate
                    for (route_addr, _), candidate in self._cid_routes.items()
                    if route_addr == addr
                ),
                None,
            )
            if replacement is None:
                self._routes.pop(addr, None)
            else:
                self._routes[addr] = replacement

    @staticmethod
    def _connection_ids(connection: QuicConnectionBackend) -> tuple[bytes, ...]:
        ids: set[bytes] = set()
        host_cid = getattr(connection, "host_cid", None)
        if host_cid is not None:
            ids.add(host_cid)
        for connection_id in getattr(connection, "_host_cids", ()):
            cid = getattr(connection_id, "cid", None)
            if cid is not None:
                ids.add(cid)
        return tuple(ids)

    @staticmethod
    def _destination_cid(data: bytes) -> bytes | None:
        try:
            return pull_quic_header(
                Buffer(data=data), host_cid_length=8
            ).destination_cid
        except (ValueError, IndexError):
            return None

    async def run(self, max_datagram_size: int = 1200) -> None:
        """Own the shared socket receive loop until cancelled or closed."""
        while True:
            data, addr = await self.socket.recvfrom(max_datagram_size)
            await self.handle_datagram(data, addr)

    async def handle_datagram(
        self, data: bytes, addr: Any, now: float | None = None
    ) -> bool:
        route = self._routes.get(addr)
        destination_cid = self._destination_cid(data)
        if destination_cid is not None:
            route = self._cid_routes.get((addr, destination_cid), route)
        if (
            route is not None
            and destination_cid is not None
            and (addr, destination_cid) not in self._cid_routes
            and self.on_unknown is not None
        ):
            route = await self._accept_unknown(addr, data, route)
        elif route is None and self.on_unknown is not None:
            try:
                route = await self.on_unknown(addr, data)
            except (ValueError, IndexError):
                return False
            if route is not None:
                self._register_unknown(addr, destination_cid, route)
        if route is None:
            return False

        connection, handle_event = route
        timestamp = trio.current_time() if now is None else now
        connection.receive_datagram(data, addr, timestamp)
        tls = getattr(connection, "tls", None)
        if tls is not None and not connection.configuration.is_client:
            tls._request_client_certificate = True
        closed = False

        def dispatch_event(event: Any) -> None:
            nonlocal closed
            normalized = normalize_event(event)
            closed = closed or isinstance(normalized, QuicConnectionClosed)
            handle_event(normalized)

        drain_events(connection, dispatch_event)
        await flush_datagrams(connection, self.socket.sendto, timestamp)
        if closed:
            self.unregister(addr, connection)
        return True

    async def _accept_unknown(self, addr, data, existing):
        try:
            route = await self.on_unknown(addr, data)
        except (ValueError, IndexError):
            return existing
        if route is not None:
            self._register_unknown(addr, self._destination_cid(data), route)
            return route
        return existing

    def _register_unknown(self, addr, destination_cid, route) -> None:
        if addr not in self._routes:
            self._routes[addr] = route
        for cid in self._connection_ids(route[0]):
            self._cid_routes[(addr, cid)] = route
        if destination_cid is not None:
            self._cid_routes[(addr, destination_cid)] = route

    async def flush_connection(self, addr: Any, now: float | None = None) -> int:
        route = self._routes.get(addr)
        if route is None:
            return 0
        timestamp = trio.current_time() if now is None else now
        return await flush_datagrams(route[0], self.socket.sendto, timestamp)
