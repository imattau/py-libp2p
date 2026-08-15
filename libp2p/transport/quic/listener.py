from collections.abc import Callable

from multiaddr import Multiaddr
import trio

from libp2p.abc import IListener
from libp2p.custom_types import THandler

from .config import QUIC_V1_MULTIADDR_PROTOCOL
from .dispatcher import QuicDatagramDispatcher
from .driver import QuicConnectionBackend
from .socket import TrioQuicDatagramSocket


class QuicListener(IListener):
    """Bind one UDP socket and run the shared QUIC dispatcher."""

    def __init__(self, handler_function: THandler) -> None:
        self.handler = handler_function
        self._socket: TrioQuicDatagramSocket | None = None
        self._dispatcher: QuicDatagramDispatcher | None = None
        self._nursery: trio.Nursery | None = None
        self._cancel_scope: trio.CancelScope | None = None
        self._addrs: tuple[Multiaddr, ...] = ()

    async def listen(self, maddr: Multiaddr, nursery: trio.Nursery) -> bool:
        if maddr.protocols()[-1].name != QUIC_V1_MULTIADDR_PROTOCOL:
            return False
        host = maddr.value_for_protocol("ip4")
        port = maddr.value_for_protocol("udp")
        if host is None or port is None:
            return False

        try:
            socket = await TrioQuicDatagramSocket.bind(host, int(port))
        except (OSError, ValueError):
            return False

        self._socket = socket
        self._dispatcher = QuicDatagramDispatcher(socket)
        self._nursery = nursery
        self._cancel_scope = trio.CancelScope()
        nursery.start_soon(self._run_dispatcher)
        local_host, local_port = socket.getsockname()
        self._addrs = (
            Multiaddr(
                f"/ip4/{local_host}/udp/{local_port}/{QUIC_V1_MULTIADDR_PROTOCOL}"
            ),
        )
        return True

    def register_connection(
        self,
        addr: object,
        connection: QuicConnectionBackend,
        handle_event: Callable[[object], None],
    ) -> None:
        if self._dispatcher is None:
            raise RuntimeError("QUIC listener is not running")
        self._dispatcher.register(addr, connection, handle_event)

    def get_addrs(self) -> tuple[Multiaddr, ...]:
        return self._addrs

    async def close(self) -> None:
        if self._cancel_scope is not None:
            self._cancel_scope.cancel()
        if self._socket is not None:
            await self._socket.aclose()
        self._socket = None
        self._dispatcher = None
        self._addrs = ()

    async def _run_dispatcher(self) -> None:
        assert self._dispatcher is not None
        assert self._cancel_scope is not None
        with self._cancel_scope:
            await self._dispatcher.run()
