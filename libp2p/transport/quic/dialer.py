import secrets

from multiaddr import Multiaddr
import trio

from libp2p.crypto.keys import KeyPair
from libp2p.peer.id import ID

from .config import QuicTransportConfig
from .connection import create_quic_connection
from .connection_adapter import QuicConnectionAdapter
from .socket import TrioQuicDatagramSocket


class QuicDialer:
    """Create a client QUIC connection on a Trio nursery."""

    async def dial(
        self,
        host: str,
        port: int,
        key_pair: KeyPair,
        nursery: trio.Nursery,
        config: QuicTransportConfig | None = None,
        expected_peer_id: ID | None = None,
        local_address: tuple[str, int] | None = None,
        punch_target: tuple[str, int] | None = None,
    ) -> QuicConnectionAdapter:
        local_host, local_port = local_address or ("127.0.0.1", 0)
        socket = await TrioQuicDatagramSocket.bind(
            local_host, local_port, reuse_port=local_address is not None
        )
        connection = create_quic_connection(is_client=True, key_pair=key_pair)
        connection.connect((host, port), trio.current_time())
        adapter = QuicConnectionAdapter(connection, object())
        nursery.start_soon(adapter.run, socket, config)
        stop_punching = trio.Event()
        if punch_target is not None:
            nursery.start_soon(
                self._send_punch_packets, socket, punch_target, stop_punching
            )
        try:
            await adapter.wait_handshake()
        finally:
            stop_punching.set()
        if expected_peer_id is not None and adapter.remote_peer_id != expected_peer_id:
            await adapter.close()
            raise ValueError(
                "QUIC peer identity does not match the expected peer ID"
            )
        return adapter

    async def dial_multiaddr(
        self,
        maddr: Multiaddr,
        key_pair: KeyPair,
        nursery: trio.Nursery,
        config: QuicTransportConfig | None = None,
        expected_peer_id: ID | None = None,
        local_address: tuple[str, int] | None = None,
        punch: bool = False,
    ) -> QuicConnectionAdapter:
        host = maddr.value_for_protocol("ip4")
        port = maddr.value_for_protocol("udp")
        if host is None or port is None:
            raise ValueError(f"invalid QUIC multiaddr: {maddr}")
        return await self.dial(
            host,
            int(port),
            key_pair,
            nursery,
            config,
            expected_peer_id,
            local_address,
            (host, int(port)) if punch else None,
        )

    async def dial_hole_punch(
        self,
        maddr: Multiaddr,
        key_pair: KeyPair,
        nursery: trio.Nursery,
        local_address: tuple[str, int],
        config: QuicTransportConfig | None = None,
        expected_peer_id: ID | None = None,
    ) -> QuicConnectionAdapter:
        return await self.dial_multiaddr(
            maddr,
            key_pair,
            nursery,
            config,
            expected_peer_id,
            local_address,
            punch=True,
        )

    @staticmethod
    async def _send_punch_packets(socket, target, stop: trio.Event) -> None:
        while not stop.is_set():
            await socket.sendto(secrets.token_bytes(32), target)
            with trio.move_on_after(0.2):
                await stop.wait()
