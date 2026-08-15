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
