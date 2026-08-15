import pytest
from multiaddr import Multiaddr

from libp2p import new_host
from libp2p.custom_types import TProtocol
from libp2p.host.resource_manager import (
    Direction,
    LimitExceeded,
    NullResourceManager,
    ResourceLimits,
    ResourceManager,
)
from libp2p.host.resource_manager.resource_manager import (
    ResourceManagerLimits,
)
from libp2p.peer.id import ID
from libp2p.peer.peerinfo import info_from_p2p_addr
from libp2p.relay.circuit_v2.resources import (
    RelayLimits,
    RelayResourceManager,
)
from tests.utils.factories import HostFactory


def peer(num: int) -> ID:
    return ID(f"peer-{num}".encode())


def test_connection_scope_moves_from_transient_to_peer():
    peer_id = peer(1)
    manager = ResourceManager()

    conn_scope = manager.open_connection(
        Direction.OUTBOUND,
        use_fd=True,
        endpoint=Multiaddr("/ip4/127.0.0.1/tcp/1234"),
    )

    assert manager.system.stat().num_conns_outbound == 1
    assert manager.transient.stat().num_conns_outbound == 1

    conn_scope.set_peer(peer_id)

    assert manager.transient.stat().num_conns_outbound == 0
    assert manager.get_peer_scope(peer_id).stat().num_conns_outbound == 1
    assert manager.system.stat().num_conns_outbound == 1

    conn_scope.done()

    assert manager.system.stat().num_conns_outbound == 0
    assert manager.get_peer_scope(peer_id).stat().num_conns_outbound == 0


def test_stream_scope_attaches_to_protocol_and_service():
    peer_id = peer(1)
    manager = ResourceManager()
    protocol_id = TProtocol("/example/1.0.0")

    stream_scope = manager.open_stream(peer_id, Direction.INBOUND)

    assert manager.transient.stat().num_streams_inbound == 1
    assert manager.get_peer_scope(peer_id).stat().num_streams_inbound == 1

    stream_scope.set_protocol(protocol_id)
    stream_scope.set_service("identify")

    assert manager.transient.stat().num_streams_inbound == 0
    assert manager.get_protocol_scope(protocol_id).stat().num_streams_inbound == 1
    assert manager.get_service_scope("identify").stat().num_streams_inbound == 1
    assert manager.system.stat().num_streams_inbound == 1

    stream_scope.done()

    assert manager.system.stat().num_streams_inbound == 0
    assert manager.get_peer_scope(peer_id).stat().num_streams_inbound == 0
    assert manager.get_protocol_scope(protocol_id).stat().num_streams_inbound == 0
    assert manager.get_service_scope("identify").stat().num_streams_inbound == 0


def test_limits_roll_back_failed_reservations():
    manager = ResourceManager(
        ResourceManagerLimits(
            system=ResourceLimits(conns=1),
            peer_default=ResourceLimits(conns=1),
        )
    )
    first = manager.open_connection(Direction.OUTBOUND, use_fd=False)
    first.set_peer(peer(1))

    with pytest.raises(LimitExceeded):
        manager.open_connection(Direction.INBOUND, use_fd=False)

    assert manager.system.stat().num_conns == 1


def test_memory_priority_thresholds_are_enforced():
    manager = ResourceManager(ResourceManagerLimits(system=ResourceLimits(memory=100)))

    with pytest.raises(LimitExceeded):
        manager.system.reserve_memory(90, priority=100)

    manager.system.reserve_memory(90)
    assert manager.system.stat().memory == 90

    manager.system.release_memory(30)
    assert manager.system.stat().memory == 60


def test_relay_reservations_use_shared_service_resources():
    manager = ResourceManager(
        ResourceManagerLimits(
            service_default=ResourceLimits(memory=1),
        )
    )
    relay_manager = RelayResourceManager(
        RelayLimits(duration=60, data=100, max_circuit_conns=1, max_reservations=2),
        manager,
    )

    relay_manager.create_reservation(peer(1))

    with pytest.raises(LimitExceeded):
        relay_manager.create_reservation(peer(2))

    assert manager.get_service_scope("relay").stat().memory == 1
    relay_manager.close()
    assert manager.get_service_scope("relay").stat().memory == 0


def test_resource_limits_load_from_config_and_autoscale():
    limits = ResourceLimits.from_config(
        {
            "streams": 8,
            "streams_inbound": 4,
            "conns_outbound": 2,
            "memory": 1024,
        }
    )

    assert limits.streams == 8
    assert limits.streams_inbound == 4
    assert limits.conns_outbound == 2
    assert limits.memory == 1024

    scaled = ResourceManagerLimits.autoscaled(0.5)

    assert scaled.system.conns == 512
    assert scaled.transient.fd == 128
    assert scaled.peer_default.streams == 128


def test_resource_manager_limits_load_configured_scope_overrides():
    protocol_id = TProtocol("/example/1.0.0")
    peer_id = peer(1)
    limits = ResourceManagerLimits.from_config(
        {
            "system": {"streams": 10, "conns": 4},
            "service_default": {"streams": 5},
            "services": {"identify": {"streams": 1}},
            "protocols": {protocol_id: {"streams": 2}},
            "peers": {peer_id: {"conns": 1}},
        }
    )
    manager = ResourceManager(limits)

    assert manager.system.limits.streams == 10
    assert manager.system.limits.conns == 4
    assert manager.get_service_scope("unknown").limits.streams == 5
    assert manager.get_service_scope("identify").limits.streams == 1
    assert manager.get_protocol_scope(protocol_id).limits.streams == 2
    assert manager.get_peer_scope(peer_id).limits.conns == 1


def test_allowlisted_peer_bypasses_peer_default_limits():
    allowed_peer = peer(1)
    manager = ResourceManager(
        ResourceManagerLimits(
            peer_default=ResourceLimits(conns=1),
            allowlisted_peers=frozenset({allowed_peer}),
        )
    )

    first = manager.open_connection(Direction.OUTBOUND, use_fd=False)
    first.set_peer(allowed_peer)
    second = manager.open_connection(Direction.OUTBOUND, use_fd=False)
    second.set_peer(allowed_peer)

    assert manager.get_peer_scope(allowed_peer).stat().num_conns == 2


def test_allowlisted_peers_load_from_config():
    peer_id = peer(1)
    limits = ResourceManagerLimits.from_config(
        {
            "peer_default": {"conns": 1},
            "allowlisted_peers": [peer_id.to_base58()],
        }
    )
    manager = ResourceManager(limits)

    first = manager.open_connection(Direction.OUTBOUND, use_fd=False)
    first.set_peer(peer_id)
    second = manager.open_connection(Direction.OUTBOUND, use_fd=False)
    second.set_peer(peer_id)

    assert manager.get_peer_scope(peer_id).stat().num_conns == 2


def test_span_releases_resources_to_parent_on_done():
    manager = ResourceManager(ResourceManagerLimits(system=ResourceLimits(memory=100)))

    span = manager.system.begin_span()
    span.reserve_memory(40)

    assert span.stat().memory == 40
    assert manager.system.stat().memory == 40

    span.done()

    assert span.stat().memory == 0
    assert manager.system.stat().memory == 0


def test_null_resource_manager_is_unlimited():
    manager = NullResourceManager()
    scope = manager.open_connection(Direction.INBOUND, use_fd=True)
    scope.reserve_memory(10**9, priority=0)
    scope.done()

    assert manager.scope.stat().memory == 0


def test_new_host_uses_supplied_resource_manager():
    manager = ResourceManager()
    host = new_host(resource_manager=manager)

    assert host.get_network().resource_manager is manager


@pytest.mark.trio
async def test_swarm_connection_uses_resource_manager(security_protocol):
    manager = ResourceManager(
        ResourceManagerLimits(system=ResourceLimits(conns_outbound=1))
    )
    async with HostFactory.create_batch_and_listen(
        3, security_protocol=security_protocol
    ) as hosts:
        hosts[0].get_network().resource_manager = manager

        await hosts[0].connect(info_from_p2p_addr(hosts[1].get_addrs()[0]))

        assert manager.system.stat().num_conns_outbound == 1

        with pytest.raises(Exception):
            await hosts[0].connect(info_from_p2p_addr(hosts[2].get_addrs()[0]))

        assert manager.system.stat().num_conns_outbound == 1

        await hosts[0].disconnect(hosts[1].get_id())

        assert manager.system.stat().num_conns_outbound == 0


@pytest.mark.trio
async def test_swarm_stream_uses_resource_manager(security_protocol):
    manager = ResourceManager(
        ResourceManagerLimits(system=ResourceLimits(streams_outbound=1))
    )
    async with HostFactory.create_batch_and_listen(
        2, security_protocol=security_protocol
    ) as hosts:
        hosts[0].get_network().resource_manager = manager
        await hosts[0].connect(info_from_p2p_addr(hosts[1].get_addrs()[0]))

        stream = await hosts[0].get_network().new_stream(hosts[1].get_id())

        assert manager.system.stat().num_streams_outbound == 1

        with pytest.raises(Exception):
            await hosts[0].get_network().new_stream(hosts[1].get_id())

        assert manager.system.stat().num_streams_outbound == 1

        await stream.reset()

        assert manager.system.stat().num_streams_outbound == 0
