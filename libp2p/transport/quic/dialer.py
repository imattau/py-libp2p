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
    ) -> QuicConnectionAdapter:
        socket = await TrioQuicDatagramSocket.bind("127.0.0.1", 0)
        connection = create_quic_connection(is_client=True, key_pair=key_pair)
        connection.connect((host, port), trio.current_time())
        adapter = QuicConnectionAdapter(connection, object())
        nursery.start_soon(adapter.run, socket, config)
        await adapter.wait_handshake()
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
        )
