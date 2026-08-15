from collections.abc import Callable
from typing import (
    Any,
    Protocol,
)

import trio

from .backend import (
    QuicConnectionBackend,
    drain_events,
    flush_datagrams,
)
from .config import QuicTransportConfig


class QuicDatagramSocket(Protocol):
    async def recvfrom(self, max_bytes: int) -> tuple[bytes, Any]: ...

    async def sendto(self, data: bytes, addr: Any) -> None: ...


class QuicTrioDriver:
    """Drive one sans-I/O QUIC connection with a Trio datagram socket."""

    def __init__(
        self,
        connection: QuicConnectionBackend,
        socket: QuicDatagramSocket,
        handle_event: Callable[[Any], None],
        config: QuicTransportConfig | None = None,
    ) -> None:
        self.connection = connection
        self.socket = socket
        self.handle_event = handle_event
        self.config = config or QuicTransportConfig()

    async def run(self) -> None:
        """Receive datagrams and backend timer events until cancelled."""
        await self._process_backend()

        while True:
            timer = self.connection.get_timer()
            if timer is None:
                data, addr = await self.socket.recvfrom(
                    self.config.max_datagram_size
                )
            else:
                with trio.move_on_after(max(0.0, timer - trio.current_time())) as scope:
                    data, addr = await self.socket.recvfrom(
                        self.config.max_datagram_size
                    )
                if scope.cancelled_caught:
                    self.connection.handle_timer(trio.current_time())
                    await self._process_backend()
                    continue

            self.connection.receive_datagram(data, addr, trio.current_time())
            await self._process_backend()

    async def _process_backend(self) -> None:
        drain_events(self.connection, self.handle_event)
        await flush_datagrams(
            self.connection,
            self.socket.sendto,
            trio.current_time(),
        )
