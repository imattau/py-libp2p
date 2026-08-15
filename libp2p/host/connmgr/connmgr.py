from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
import math
import time

from multiaddr import Multiaddr
import trio

from libp2p.abc import (
    INetConn,
    INetStream,
    INetwork,
    INotifee,
)
from libp2p.network.events import (
    EventConnected,
    EventDisconnected,
    EventSubscription,
)
from libp2p.peer.id import (
    ID,
)
from libp2p.tools.async_service import (
    Service,
)

DEFAULT_GRACE_PERIOD = 20
DEFAULT_SILENCE_PERIOD = 10


@dataclass(frozen=True)
class ConnManagerConfig:
    low_water: int
    high_water: int
    grace_period: float = DEFAULT_GRACE_PERIOD
    silence_period: float = DEFAULT_SILENCE_PERIOD

    def __post_init__(self) -> None:
        if self.low_water < 0:
            raise ValueError("low_water must be non-negative")
        if self.high_water < self.low_water:
            raise ValueError("high_water must be greater than or equal to low_water")
        if self.grace_period < 0:
            raise ValueError("grace_period must be non-negative")
        if self.silence_period < 0:
            raise ValueError("silence_period must be non-negative")


@dataclass
class DecayingTag:
    name: str
    value: float
    decay: float
    bump: float = 0
    last_updated: float = field(default_factory=time.monotonic)

    def current_value(self, now: float | None = None) -> float:
        now = time.monotonic() if now is None else now
        if self.decay <= 0:
            return 0
        if self.decay >= 1:
            return self.value
        elapsed = max(0.0, now - self.last_updated)
        return self.value * (self.decay**elapsed)

    def touch(self, delta: float = 0) -> float:
        value = self.current_value()
        self.value = max(0.0, value + delta)
        self.last_updated = time.monotonic()
        return self.value

    def bump_value(self) -> float:
        return self.touch(self.bump)


@dataclass
class TagInfo:
    first_seen: float = field(default_factory=time.monotonic)
    tags: dict[str, float] = field(default_factory=dict)
    decaying_tags: dict[str, DecayingTag] = field(default_factory=dict)

    def value(self, now: float | None = None) -> float:
        fixed = sum(self.tags.values())
        decaying = sum(tag.current_value(now) for tag in self.decaying_tags.values())
        return fixed + decaying


class BasicConnMgr(Service, INotifee):
    """
    Connection manager ported from go-libp2p's BasicConnMgr model.

    py-libp2p currently keeps at most one network connection per peer, so trimming is
    peer-oriented: when the high watermark is exceeded, the manager closes lowest-value
    unprotected peers until the low watermark is reached.
    """

    event_bus_consumer = True

    def __init__(self, config: ConnManagerConfig) -> None:
        self.config = config
        self._peer_info: dict[ID, TagInfo] = {}
        self._protected: dict[ID, set[str]] = {}
        self._network: INetwork | None = None
        self._event_bus = None
        self._last_trim = 0.0
        self._lock = trio.Lock()

    @classmethod
    def new(
        cls,
        low_water: int,
        high_water: int,
        grace_period: float = DEFAULT_GRACE_PERIOD,
        silence_period: float = DEFAULT_SILENCE_PERIOD,
    ) -> "BasicConnMgr":
        return cls(
            ConnManagerConfig(
                low_water=low_water,
                high_water=high_water,
                grace_period=grace_period,
                silence_period=silence_period,
            )
        )

    def get_tag_info(self, peer_id: ID) -> TagInfo:
        return self._get_or_create(peer_id)

    def tag_peer(self, peer_id: ID, tag: str, value: float) -> None:
        self._get_or_create(peer_id).tags[tag] = value

    def untag_peer(self, peer_id: ID, tag: str) -> None:
        info = self._peer_info.get(peer_id)
        if info is not None:
            info.tags.pop(tag, None)

    def upsert_tag(
        self,
        peer_id: ID,
        tag: str,
        update: Callable[[float | None], float],
    ) -> float:
        info = self._get_or_create(peer_id)
        next_value = update(info.tags.get(tag))
        info.tags[tag] = next_value
        return next_value

    def protect(self, peer_id: ID, tag: str) -> None:
        self._protected.setdefault(peer_id, set()).add(tag)

    def unprotect(self, peer_id: ID, tag: str) -> bool:
        tags = self._protected.get(peer_id)
        if tags is None:
            return False
        tags.discard(tag)
        if not tags:
            self._protected.pop(peer_id, None)
            return False
        return True

    def is_protected(self, peer_id: ID, tag: str | None = None) -> bool:
        tags = self._protected.get(peer_id)
        if tags is None:
            return False
        if tag is None:
            return True
        return tag in tags

    def register_decaying_tag(
        self,
        peer_id: ID,
        tag: str,
        value: float,
        *,
        decay: float,
        bump: float = 0,
    ) -> DecayingTag:
        if not math.isfinite(decay) or decay < 0:
            raise ValueError("decay must be a non-negative finite value")
        info = self._get_or_create(peer_id)
        decaying_tag = DecayingTag(tag, value, decay, bump)
        info.decaying_tags[tag] = decaying_tag
        return decaying_tag

    def bump_decaying_tag(
        self, peer_id: ID, tag: str, delta: float | None = None
    ) -> float:
        info = self._peer_info.get(peer_id)
        if info is None or tag not in info.decaying_tags:
            raise KeyError(tag)
        decaying_tag = info.decaying_tags[tag]
        if delta is None:
            return decaying_tag.bump_value()
        return decaying_tag.touch(delta)

    async def trim_open_conns(self, network: INetwork) -> list[ID]:
        async with self._lock:
            return await self._trim_open_conns(network)

    async def run(self) -> None:
        if self._event_bus is not None:
            connected = await self._event_bus.subscribe(EventConnected)
            disconnected = await self._event_bus.subscribe(EventDisconnected)
            self.manager.run_daemon_task(
                self._consume_connected_events, connected
            )
            self.manager.run_daemon_task(
                self._consume_disconnected_events, disconnected
            )
        else:
            connected = disconnected = None

        try:
            while True:
                with trio.move_on_after(self._background_interval()):
                    await self.manager.wait_finished()
                    return

                network = self._network
                if (
                    network is not None
                    and len(network.connections) >= self.config.high_water
                ):
                    await self.trim_open_conns(network)
        finally:
            if connected is not None:
                await connected.unsubscribe()
            if disconnected is not None:
                await disconnected.unsubscribe()

    def bind_event_bus(self, network: INetwork) -> None:
        self._network = network
        self._event_bus = network.get_event_bus()

    async def _consume_connected_events(
        self, subscription: EventSubscription[EventConnected]
    ) -> None:
        async for event in subscription:
            if self._network is not None:
                await self.connected(self._network, event.conn)

    async def _consume_disconnected_events(
        self, subscription: EventSubscription[EventDisconnected]
    ) -> None:
        async for event in subscription:
            if self._network is not None:
                await self.disconnected(self._network, event.conn)

    async def force_trim(self, network: INetwork) -> list[ID]:
        async with self._lock:
            conn_count = len(network.connections)
            close_count = conn_count - self.config.low_water
            if close_count <= 0:
                return []

            unprotected = self._sorted_candidates(network, include_protected=False)
            protected = self._sorted_candidates(network, include_protected=True)
            protected = [
                item for item in protected if self.is_protected(item[2])
            ]
            closed: list[ID] = []
            for _, _, peer_id in [*unprotected, *protected]:
                if len(closed) >= close_count:
                    break
                if peer_id not in network.connections:
                    continue
                await network.close_peer(peer_id)
                closed.append(peer_id)
            self._last_trim = time.monotonic()
            return closed

    async def opened_stream(self, network: INetwork, stream: INetStream) -> None:
        self._observe_network(network)
        await trio.lowlevel.checkpoint()

    async def closed_stream(self, network: INetwork, stream: INetStream) -> None:
        self._observe_network(network)
        await trio.lowlevel.checkpoint()

    async def connected(self, network: INetwork, conn: INetConn) -> None:
        self._observe_network(network)
        self._get_or_create(conn.muxed_conn.peer_id)
        if len(network.connections) > self.config.high_water:
            await self.trim_open_conns(network)

    async def disconnected(self, network: INetwork, conn: INetConn) -> None:
        self._observe_network(network)
        self._peer_info.pop(conn.muxed_conn.peer_id, None)
        await trio.lowlevel.checkpoint()

    async def listen(self, network: INetwork, multiaddr: Multiaddr) -> None:
        self._observe_network(network)
        await trio.lowlevel.checkpoint()

    async def listen_close(self, network: INetwork, multiaddr: Multiaddr) -> None:
        self._observe_network(network)
        await trio.lowlevel.checkpoint()

    async def _trim_open_conns(self, network: INetwork) -> list[ID]:
        if self.config.low_water == 0 or self.config.high_water == 0:
            return []

        now = time.monotonic()
        if now - self._last_trim < self.config.silence_period:
            return []
        self._last_trim = now

        conn_count = len(network.connections)
        if conn_count <= self.config.low_water:
            return []

        candidates = self._sorted_candidates(
            network,
            include_protected=False,
            min_first_seen=now - self.config.grace_period,
            now=now,
        )

        if len(candidates) < self.config.low_water:
            return []

        close_count = len(candidates) - self.config.low_water
        closed: list[ID] = []
        for _, _, peer_id in candidates[:close_count]:
            if peer_id not in network.connections:
                continue
            await network.close_peer(peer_id)
            closed.append(peer_id)
        return closed

    def _sorted_candidates(
        self,
        network: INetwork,
        *,
        include_protected: bool,
        min_first_seen: float | None = None,
        now: float | None = None,
    ) -> list[tuple[float, float, ID]]:
        now = time.monotonic() if now is None else now
        candidates: list[tuple[float, float, ID]] = []
        for peer_id in network.connections:
            if not include_protected and self.is_protected(peer_id):
                continue
            info = self._get_or_create(peer_id, first_seen=now)
            if min_first_seen is not None and info.first_seen > min_first_seen:
                continue
            candidates.append((info.value(now), info.first_seen, peer_id))
        candidates.sort(key=lambda item: (item[0], item[1]))
        return candidates

    def _get_or_create(self, peer_id: ID, first_seen: float | None = None) -> TagInfo:
        if peer_id not in self._peer_info:
            if first_seen is None:
                self._peer_info[peer_id] = TagInfo()
            else:
                self._peer_info[peer_id] = TagInfo(first_seen=first_seen)
        return self._peer_info[peer_id]

    def _observe_network(self, network: INetwork) -> None:
        if self._network is None:
            self._network = network

    def _background_interval(self) -> float:
        if self.config.silence_period > 0:
            return self.config.silence_period
        if self.config.grace_period > 0:
            return self.config.grace_period / 2
        return 0.01
