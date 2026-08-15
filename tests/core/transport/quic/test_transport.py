import pytest
from multiaddr import Multiaddr
import trio

from libp2p import new_swarm
from libp2p.crypto.ed25519 import create_new_key_pair
from libp2p.peer.peerstore import PeerStore
from libp2p.tools.async_service import background_trio_service
from libp2p.transport.quic.transport import (
    QuicTransport,
    _is_quic_v1,
)


def test_transport_creates_identity_bound_listener():
    transport = QuicTransport(create_new_key_pair(seed=b"u" * 32))

    listener = transport.create_listener(lambda connection: None)

    assert listener.key_pair == transport.key_pair


@pytest.mark.trio
async def test_transport_requires_nursery_for_dial():
    transport = QuicTransport(create_new_key_pair(seed=b"v" * 32))

    with pytest.raises(RuntimeError, match="requires a Trio nursery"):
        await transport.dial(Multiaddr("/ip4/127.0.0.1/udp/1/quic-v1"))


def test_transport_rejects_non_quic_multiaddr():
    assert not _is_quic_v1(Multiaddr("/ip4/127.0.0.1/udp/1/quic"))


def test_transport_uses_native_connection_path():
    transport = QuicTransport(create_new_key_pair(seed=b"w" * 32))

    assert transport.native_connections is True


@pytest.mark.trio
async def test_native_quic_transport_integrates_with_swarm():
    key_pair_0 = create_new_key_pair(seed=b"x" * 32)
    key_pair_1 = create_new_key_pair(seed=b"y" * 32)
    quic_addr = Multiaddr("/ip4/127.0.0.1/udp/0/quic-v1")
    swarm_0 = new_swarm(
        key_pair=key_pair_0,
        peerstore_opt=PeerStore(),
        listen_addrs=[quic_addr],
    )
    swarm_1 = new_swarm(
        key_pair=key_pair_1,
        peerstore_opt=PeerStore(),
        listen_addrs=[quic_addr],
    )

    async with background_trio_service(swarm_0), background_trio_service(swarm_1):
        assert await swarm_1.listen(quic_addr)
        listen_addr = next(iter(swarm_1.listeners.values())).get_addrs()[0]
        swarm_0.peerstore.add_addrs(swarm_1.get_peer_id(), [listen_addr], 60_000)

        stream = await swarm_0.new_stream(swarm_1.get_peer_id())

        assert swarm_1.get_peer_id() in swarm_0.connections
        assert swarm_0.get_peer_id() in swarm_1.connections
        await stream.close()
