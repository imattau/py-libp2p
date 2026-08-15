import pytest
from multiaddr import Multiaddr

from libp2p.transport.quic.listener import QuicListener


@pytest.mark.trio
async def test_listener_rejects_non_quic_addresses(nursery):
    listener = QuicListener(lambda connection: None)

    assert not await listener.listen(
        Multiaddr("/ip4/127.0.0.1/udp/1234/quic"), nursery
    )
    assert listener.get_addrs() == ()
