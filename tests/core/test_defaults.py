import pytest

from libp2p import new_swarm
from libp2p.security.noise.transport import PROTOCOL_ID as NOISE_PROTOCOL_ID
from libp2p.security.tls import TLS_PROTOCOL_ID
from libp2p.stream_muxer.yamux.yamux import PROTOCOL_ID as YAMUX_PROTOCOL_ID


@pytest.mark.trio
async def test_default_upgrader_advertises_modern_protocols_only() -> None:
    swarm = new_swarm()
    try:
        assert list(swarm.upgrader.security_multistream.transports) == [
            NOISE_PROTOCOL_ID,
            TLS_PROTOCOL_ID,
        ]
        assert list(swarm.upgrader.muxer_multistream.transports) == [
            YAMUX_PROTOCOL_ID
        ]
    finally:
        await swarm.close()
