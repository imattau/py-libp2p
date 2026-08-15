import pytest
from multiaddr import Multiaddr
import trio

from libp2p.crypto.ed25519 import create_new_key_pair
from libp2p.peer.id import ID
from libp2p.transport.quic.dialer import QuicDialer
from libp2p.transport.quic.listener import QuicListener


@pytest.mark.trio
async def test_dialer_completes_localhost_quic_handshake():
    server_key_pair = create_new_key_pair(seed=b"s" * 32)
    client_key_pair = create_new_key_pair(seed=b"c" * 32)
    server_connections = []
    server_ready = trio.Event()

    async def handle_server_connection(connection):
        server_connections.append(connection)
        await connection.wait_handshake()
        server_ready.set()
        await trio.sleep_forever()

    listener = QuicListener(handle_server_connection, server_key_pair)
    async with trio.open_nursery() as nursery:
        assert await listener.listen(
            Multiaddr("/ip4/127.0.0.1/udp/0/quic-v1"), nursery
        )
        address = listener.get_addrs()[0]
        port = int(address.value_for_protocol("udp"))
        client = await QuicDialer().dial(
            "127.0.0.1", port, client_key_pair, nursery
        )
        await server_ready.wait()
        assert client.connection.configuration.is_client
        assert client.remote_peer_id == ID.from_pubkey(server_key_pair.public_key)
        assert server_connections
        assert server_connections[0].remote_peer_id == ID.from_pubkey(
            client_key_pair.public_key
        )
        nursery.cancel_scope.cancel()

    await listener.close()
