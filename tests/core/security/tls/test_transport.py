import pytest
from multiaddr import Multiaddr
import trio
from trio.testing import memory_stream_pair

from libp2p import new_swarm
from libp2p.crypto.ed25519 import create_new_key_pair
from libp2p.peer.peerstore import PeerStore
from libp2p.security.tls import TLS_PROTOCOL_ID
from libp2p.security.tls.transport import TLSTransport
from libp2p.tools.async_service import background_trio_service


class RawMemoryConnection:
    def __init__(self, stream):
        self.stream = stream

    async def read(self, n=None):
        return await self.stream.receive_some(n or 16384)

    async def write(self, data):
        await self.stream.send_all(data)

    async def close(self):
        await self.stream.aclose()

    def get_remote_address(self):
        return None


@pytest.mark.trio
async def test_tls_transport_authenticates_and_encrypts_memory_stream():
    stream_0, stream_1 = memory_stream_pair()
    key_pair_0 = create_new_key_pair(seed=b"0" * 32)
    key_pair_1 = create_new_key_pair(seed=b"1" * 32)
    transport_0 = TLSTransport(key_pair_0)
    transport_1 = TLSTransport(key_pair_1)
    sessions = []

    async def secure_outbound():
        sessions.append(
            await transport_0.secure_outbound(
                RawMemoryConnection(stream_0), transport_1.identity.peer_id
            )
        )

    async def secure_inbound():
        sessions.append(
            await transport_1.secure_inbound(RawMemoryConnection(stream_1))
        )

    async with trio.open_nursery() as nursery:
        nursery.start_soon(secure_outbound)
        nursery.start_soon(secure_inbound)

    outbound, inbound = sessions
    assert outbound.get_remote_peer() == transport_1.identity.peer_id
    assert inbound.get_remote_peer() == transport_0.identity.peer_id

    await outbound.write(b"encrypted")
    assert await inbound.read() == b"encrypted"
    await outbound.close()
    await inbound.close()


@pytest.mark.trio
async def test_tls_transport_rejects_unexpected_peer_id():
    stream_0, stream_1 = memory_stream_pair()
    key_pair_0 = create_new_key_pair(seed=b"2" * 32)
    key_pair_1 = create_new_key_pair(seed=b"3" * 32)
    key_pair_unexpected = create_new_key_pair(seed=b"4" * 32)
    transport_0 = TLSTransport(key_pair_0)
    transport_1 = TLSTransport(key_pair_1)

    async def secure_outbound():
        with pytest.raises(ValueError, match="does not match"):
            await transport_0.secure_outbound(
                RawMemoryConnection(stream_0),
                TLSTransport(key_pair_unexpected).identity.peer_id,
            )

    async def secure_inbound():
        await transport_1.secure_inbound(RawMemoryConnection(stream_1))

    async with trio.open_nursery() as nursery:
        nursery.start_soon(secure_outbound)
        nursery.start_soon(secure_inbound)


@pytest.mark.trio
async def test_tls_transport_negotiates_through_swarm():
    key_pair_0 = create_new_key_pair(seed=b"5" * 32)
    key_pair_1 = create_new_key_pair(seed=b"6" * 32)
    swarm_0 = new_swarm(
        key_pair=key_pair_0,
        peerstore_opt=PeerStore(),
        sec_opt={TLS_PROTOCOL_ID: TLSTransport(key_pair_0)},
    )
    swarm_1 = new_swarm(
        key_pair=key_pair_1,
        peerstore_opt=PeerStore(),
        sec_opt={TLS_PROTOCOL_ID: TLSTransport(key_pair_1)},
    )

    async with background_trio_service(swarm_0), background_trio_service(swarm_1):
        assert await swarm_1.listen(Multiaddr("/ip4/127.0.0.1/tcp/0"))
        listen_addr = next(iter(swarm_1.listeners.values())).get_addrs()[0]
        swarm_0.peerstore.add_addrs(swarm_1.get_peer_id(), [listen_addr], 60_000)

        connection = await swarm_0.dial_peer(swarm_1.get_peer_id())

        assert connection.muxed_conn.peer_id == swarm_1.get_peer_id()
