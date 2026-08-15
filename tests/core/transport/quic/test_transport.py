import pytest
from multiaddr import Multiaddr

from libp2p.crypto.ed25519 import create_new_key_pair
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
