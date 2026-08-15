import pytest
import trio
from trio.testing import memory_stream_pair

from libp2p.crypto.ed25519 import create_new_key_pair
from libp2p.security.tls.transport import TLSTransport


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
