from dataclasses import dataclass

import pytest
from multiaddr import Multiaddr
import trio

from libp2p.network.events import (
    EventBus,
    EventClosedStream,
    EventConnected,
    EventDisconnected,
    EventListen,
    EventListenClose,
    EventOpenedStream,
)
from libp2p.peer.id import (
    ID,
)
from libp2p.tools.async_service import (
    background_trio_service,
)
from libp2p.tools.constants import (
    LISTEN_MADDR,
)
from libp2p.tools.utils import (
    connect_swarm,
)
from tests.utils.factories import (
    SwarmFactory,
)


@dataclass
class FakeMuxedConn:
    peer_id: ID


@dataclass
class FakeConn:
    muxed_conn: FakeMuxedConn


async def receive_with_timeout(subscription, timeout=1.0):
    with trio.fail_after(timeout):
        return await subscription.receive()


@pytest.mark.trio
async def test_event_bus_filters_by_event_type():
    event_bus = EventBus()
    connected = await event_bus.subscribe(EventConnected)

    await event_bus.publish(EventListen(Multiaddr("/ip4/127.0.0.1/tcp/0")))

    with trio.move_on_after(0.05) as cancel_scope:
        await connected.receive()
    assert cancel_scope.cancelled_caught

    conn = FakeConn(FakeMuxedConn(ID(b"peer")))
    await event_bus.publish(EventConnected(conn))

    event = await receive_with_timeout(connected)
    assert event.conn is conn


@pytest.mark.trio
async def test_swarm_event_bus_emits_connection_and_stream_events(security_protocol):
    async with SwarmFactory.create_batch_and_listen(
        2, security_protocol=security_protocol
    ) as swarms:
        peer_id = swarms[1].get_peer_id()
        event_bus = swarms[0].get_event_bus()
        connected = await event_bus.subscribe(EventConnected)
        opened_stream = await event_bus.subscribe(EventOpenedStream)
        closed_stream = await event_bus.subscribe(EventClosedStream)
        disconnected = await event_bus.subscribe(EventDisconnected)

        await connect_swarm(swarms[0], swarms[1])

        connected_event = await receive_with_timeout(connected)
        assert connected_event.conn.muxed_conn.peer_id == peer_id

        stream = await swarms[0].new_stream(peer_id)

        opened_event = await receive_with_timeout(opened_stream)
        assert opened_event.stream is stream

        await stream.reset()

        closed_event = await receive_with_timeout(closed_stream)
        assert closed_event.stream is stream

        await swarms[0].close_peer(peer_id)

        disconnected_event = await receive_with_timeout(disconnected)
        assert disconnected_event.conn.muxed_conn.peer_id == peer_id


@pytest.mark.trio
async def test_swarm_event_bus_emits_listen_lifecycle(security_protocol):
    swarm = SwarmFactory(security_protocol=security_protocol)
    event_bus = swarm.get_event_bus()
    listen = await event_bus.subscribe(EventListen)
    listen_close = await event_bus.subscribe(EventListenClose)

    async with background_trio_service(swarm):
        assert await swarm.listen(LISTEN_MADDR)

        listen_event = await receive_with_timeout(listen)
        assert listen_event.multiaddr == LISTEN_MADDR

        await swarm.close()

        listen_close_event = await receive_with_timeout(listen_close)
        assert listen_close_event.multiaddr == LISTEN_MADDR
