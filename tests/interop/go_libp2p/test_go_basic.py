import os
from pathlib import Path

import pytest

GO_P2PD = Path(os.environ.get("GOPATH", "")) / "bin" / "p2pd"
pytestmark = pytest.mark.skipif(
    not GO_P2PD.is_file(),
    reason="go-libp2p p2pd is not installed; set GOPATH and build p2pd",
)


@pytest.mark.trio
async def test_py_libp2p_can_ping_go_libp2p():
    from libp2p.host.ping import PingService
    from libp2p.security.noise.transport import PROTOCOL_ID as NOISE_PROTOCOL_ID
    from tests.utils.factories import HostFactory
    from tests.utils.interop.daemon import make_p2pd

    async with HostFactory.create_batch_and_listen(1) as hosts:
        host = hosts[0]
        async with make_p2pd(42000, 42001, NOISE_PROTOCOL_ID) as daemon:
            await host.connect(daemon.peer_info)
            rtts = await PingService(host).ping(daemon.peer_id)

            assert rtts
            assert all(rtt >= 0 for rtt in rtts)


@pytest.mark.trio
async def test_go_libp2p_can_ping_py_libp2p():
    from p2pclient.libp2p_stubs.peer.id import ID as StubID

    from libp2p.security.noise.transport import PROTOCOL_ID as NOISE_PROTOCOL_ID
    from tests.utils.factories import HostFactory
    from tests.utils.interop.daemon import make_p2pd

    async with HostFactory.create_batch_and_listen(1) as hosts:
        host = hosts[0]
        async with make_p2pd(42002, 42003, NOISE_PROTOCOL_ID) as daemon:
            host_id = StubID(host.get_id().to_bytes())
            await daemon.control.connect(host_id, host.get_addrs())
            _, stream = await daemon.control.stream_open(
                host_id, ["/ipfs/ping/1.0.0"]
            )
            payload = b"p" * 32
            await stream.send(payload)
            assert await stream.receive_exactly(len(payload)) == payload
            await stream.aclose()
