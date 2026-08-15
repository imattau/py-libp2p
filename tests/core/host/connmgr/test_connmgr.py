from dataclasses import dataclass

import pytest
import trio

from libp2p.host.connmgr import (
    BasicConnMgr,
)
from libp2p.peer.id import (
    ID,
)
from libp2p.peer.peerinfo import (
    info_from_p2p_addr,
)
from libp2p.tools.async_service import (
    background_trio_service,
)
from tests.utils.factories import (
    HostFactory,
)


@dataclass
class FakeMuxedConn:
    peer_id: ID


class FakeConn:
    def __init__(self, peer_id: ID) -> None:
        self.muxed_conn = FakeMuxedConn(peer_id)
        self.event_started = trio.Event()

    async def close(self) -> None:
        pass

    async def new_stream(self):
        raise NotImplementedError

    def get_streams(self):
        return ()


class FakeNetwork:
    def __init__(self, peer_ids: list[ID]) -> None:
        self.peerstore = None
        self.listeners = {}
        self.connections = {peer_id: FakeConn(peer_id) for peer_id in peer_ids}
        self.closed = []

    def get_peer_id(self):
        return ID(b"local")

    async def dial_peer(self, peer_id):
        return self.connections[peer_id]

    async def new_stream(self, peer_id):
        raise NotImplementedError

    def set_stream_handler(self, stream_handler):
        pass

    async def listen(self, *multiaddrs):
        return True

    def register_notifee(self, notifee):
        pass

    async def close(self):
        pass

    async def close_peer(self, peer_id):
        self.closed.append(peer_id)
        self.connections.pop(peer_id, None)


def peer(num: int) -> ID:
    return ID(f"peer-{num}".encode())


@pytest.mark.trio
async def test_trim_closes_lowest_value_peers_to_low_water():
    peer_ids = [peer(num) for num in range(5)]
    network = FakeNetwork(peer_ids)
    connmgr = BasicConnMgr.new(
        low_water=2,
        high_water=3,
        grace_period=0,
        silence_period=0,
    )
    for index, peer_id in enumerate(peer_ids):
        connmgr.tag_peer(peer_id, "score", index)

    closed = await connmgr.trim_open_conns(network)

    assert closed == peer_ids[:3]
    assert set(network.connections) == set(peer_ids[3:])


@pytest.mark.trio
async def test_trim_respects_protection_and_grace_period():
    peer_ids = [peer(num) for num in range(4)]
    network = FakeNetwork(peer_ids)
    connmgr = BasicConnMgr.new(
        low_water=1,
        high_water=2,
        grace_period=0,
        silence_period=0,
    )
    connmgr.protect(peer_ids[0], "bootstrap")
    connmgr.get_tag_info(peer_ids[1]).first_seen = 10**12

    closed = await connmgr.trim_open_conns(network)

    assert closed == [peer_ids[2]]
    assert peer_ids[0] in network.connections
    assert peer_ids[1] in network.connections
    assert peer_ids[3] in network.connections


@pytest.mark.trio
async def test_connected_event_trims_when_high_water_exceeded():
    peer_ids = [peer(num) for num in range(4)]
    network = FakeNetwork(peer_ids)
    connmgr = BasicConnMgr.new(
        low_water=2,
        high_water=3,
        grace_period=0,
        silence_period=0,
    )
    for index, peer_id in enumerate(peer_ids):
        connmgr.tag_peer(peer_id, "score", index)

    await connmgr.connected(network, network.connections[peer_ids[-1]])

    assert network.closed == peer_ids[:2]


def test_decaying_tag_value_decays_and_can_be_bumped():
    peer_id = peer(0)
    connmgr = BasicConnMgr.new(low_water=0, high_water=1)
    tag = connmgr.register_decaying_tag(peer_id, "recent", 8, decay=0.5, bump=3)

    tag.last_updated -= 1
    assert tag.current_value() == pytest.approx(4, rel=0.2)

    bumped = connmgr.bump_decaying_tag(peer_id, "recent")
    assert bumped == pytest.approx(7, rel=0.2)
    assert connmgr.get_tag_info(peer_id).value() == pytest.approx(bumped, rel=0.01)


def test_protect_unprotect_tracks_multiple_reasons():
    peer_id = peer(0)
    connmgr = BasicConnMgr.new(low_water=0, high_water=1)

    connmgr.protect(peer_id, "relay")
    connmgr.protect(peer_id, "bootstrap")

    assert connmgr.is_protected(peer_id)
    assert connmgr.unprotect(peer_id, "relay") is True
    assert connmgr.unprotect(peer_id, "bootstrap") is False
    assert not connmgr.is_protected(peer_id)


@pytest.mark.trio
async def test_force_trim_uses_protected_peers_only_after_unprotected():
    peer_ids = [peer(num) for num in range(4)]
    network = FakeNetwork(peer_ids)
    connmgr = BasicConnMgr.new(low_water=1, high_water=3)
    connmgr.protect(peer_ids[0], "bootstrap")
    for index, peer_id in enumerate(peer_ids):
        connmgr.tag_peer(peer_id, "score", index)

    closed = await connmgr.force_trim(network)

    assert closed == [peer_ids[1], peer_ids[2], peer_ids[3]]
    assert list(network.connections) == [peer_ids[0]]


@pytest.mark.trio
async def test_disconnected_removes_tag_info_but_keeps_protection():
    peer_id = peer(0)
    network = FakeNetwork([peer_id])
    connmgr = BasicConnMgr.new(low_water=0, high_water=1)
    connmgr.tag_peer(peer_id, "score", 10)
    connmgr.protect(peer_id, "bootstrap")

    await connmgr.disconnected(network, network.connections[peer_id])

    assert connmgr.get_tag_info(peer_id).value() == 0
    assert connmgr.is_protected(peer_id, "bootstrap")


@pytest.mark.trio
async def test_conn_manager_trims_real_swarm_connections(security_protocol):
    connmgr = BasicConnMgr.new(
        low_water=1,
        high_water=2,
        grace_period=0,
        silence_period=0,
    )
    async with HostFactory.create_batch_and_listen(
        4, security_protocol=security_protocol
    ) as hosts:
        managed_host = hosts[0]
        managed_host.get_network().register_notifee(connmgr)
        peers = hosts[1:]

        for index, host in enumerate(peers):
            connmgr.tag_peer(host.get_id(), "score", index)
            await managed_host.connect(info_from_p2p_addr(host.get_addrs()[0]))

        await trio.sleep(0.2)

        assert managed_host.get_connected_peers() == [peers[-1].get_id()]


@pytest.mark.trio
async def test_conn_manager_background_service_trims_at_high_water(
    security_protocol,
):
    connmgr = BasicConnMgr.new(
        low_water=1,
        high_water=2,
        grace_period=0,
        silence_period=0.05,
    )
    async with (
        HostFactory.create_batch_and_listen(
            3, security_protocol=security_protocol
        ) as hosts,
        background_trio_service(connmgr),
    ):
        managed_host = hosts[0]
        managed_host.get_network().register_notifee(connmgr)
        peers = hosts[1:]

        for index, host in enumerate(peers):
            connmgr.tag_peer(host.get_id(), "score", index)
            await managed_host.connect(info_from_p2p_addr(host.get_addrs()[0]))

        with trio.fail_after(1):
            while managed_host.get_connected_peers() != [peers[-1].get_id()]:
                await trio.sleep(0.01)


@pytest.mark.trio
async def test_conn_manager_consumes_event_bus(security_protocol):
    connmgr = BasicConnMgr.new(
        low_water=1,
        high_water=2,
        grace_period=0,
        silence_period=0,
    )
    async with HostFactory.create_batch_and_listen(
        3, security_protocol=security_protocol
    ) as hosts:
        managed_host = hosts[0]
        connmgr.bind_event_bus(managed_host.get_network())
        peers = hosts[1:]

        async with background_trio_service(connmgr):
            for index, host in enumerate(peers):
                connmgr.tag_peer(host.get_id(), "score", index)
                await managed_host.connect(info_from_p2p_addr(host.get_addrs()[0]))

            with trio.fail_after(1):
                while managed_host.get_connected_peers() != [peers[-1].get_id()]:
                    await trio.sleep(0.01)
