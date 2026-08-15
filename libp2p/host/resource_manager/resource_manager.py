from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any, TypeAlias, TypeVar

from multiaddr import Multiaddr

from libp2p.custom_types import TProtocol
from libp2p.peer.id import ID

RESERVATION_PRIORITY_ALWAYS = 255
TKey = TypeVar("TKey")


class LimitExceeded(Exception):
    """Raised when a resource reservation would exceed a scope limit."""


class Direction(Enum):
    INBOUND = "inbound"
    OUTBOUND = "outbound"


@dataclass(frozen=True)
class ScopeStat:
    num_streams_inbound: int = 0
    num_streams_outbound: int = 0
    num_conns_inbound: int = 0
    num_conns_outbound: int = 0
    num_fd: int = 0
    memory: int = 0

    def plus(self, other: "ScopeStat") -> "ScopeStat":
        return ScopeStat(
            num_streams_inbound=self.num_streams_inbound
            + other.num_streams_inbound,
            num_streams_outbound=self.num_streams_outbound
            + other.num_streams_outbound,
            num_conns_inbound=self.num_conns_inbound + other.num_conns_inbound,
            num_conns_outbound=self.num_conns_outbound + other.num_conns_outbound,
            num_fd=self.num_fd + other.num_fd,
            memory=self.memory + other.memory,
        )

    def minus(self, other: "ScopeStat") -> "ScopeStat":
        return ScopeStat(
            num_streams_inbound=self.num_streams_inbound
            - other.num_streams_inbound,
            num_streams_outbound=self.num_streams_outbound
            - other.num_streams_outbound,
            num_conns_inbound=self.num_conns_inbound - other.num_conns_inbound,
            num_conns_outbound=self.num_conns_outbound - other.num_conns_outbound,
            num_fd=self.num_fd - other.num_fd,
            memory=self.memory - other.memory,
        )

    @property
    def num_streams(self) -> int:
        return self.num_streams_inbound + self.num_streams_outbound

    @property
    def num_conns(self) -> int:
        return self.num_conns_inbound + self.num_conns_outbound


@dataclass(frozen=True)
class ResourceLimits:
    streams: int | None = None
    streams_inbound: int | None = None
    streams_outbound: int | None = None
    conns: int | None = None
    conns_inbound: int | None = None
    conns_outbound: int | None = None
    fd: int | None = None
    memory: int | None = None

    @classmethod
    def from_config(cls, config: Mapping[str, int | None]) -> "ResourceLimits":
        return cls(
            streams=config.get("streams"),
            streams_inbound=config.get("streams_inbound"),
            streams_outbound=config.get("streams_outbound"),
            conns=config.get("conns"),
            conns_inbound=config.get("conns_inbound"),
            conns_outbound=config.get("conns_outbound"),
            fd=config.get("fd"),
            memory=config.get("memory"),
        )

    def scale(self, factor: float) -> "ResourceLimits":
        if factor <= 0:
            raise ValueError("scale factor must be positive")

        def scale_limit(limit: int | None) -> int | None:
            if limit is None:
                return None
            return max(1, int(limit * factor))

        return ResourceLimits(
            streams=scale_limit(self.streams),
            streams_inbound=scale_limit(self.streams_inbound),
            streams_outbound=scale_limit(self.streams_outbound),
            conns=scale_limit(self.conns),
            conns_inbound=scale_limit(self.conns_inbound),
            conns_outbound=scale_limit(self.conns_outbound),
            fd=scale_limit(self.fd),
            memory=scale_limit(self.memory),
        )

    def check(self, stat: ScopeStat, *, priority: int) -> None:
        checks = (
            (self.streams, stat.num_streams, "streams"),
            (self.streams_inbound, stat.num_streams_inbound, "inbound streams"),
            (self.streams_outbound, stat.num_streams_outbound, "outbound streams"),
            (self.conns, stat.num_conns, "connections"),
            (self.conns_inbound, stat.num_conns_inbound, "inbound connections"),
            (self.conns_outbound, stat.num_conns_outbound, "outbound connections"),
            (self.fd, stat.num_fd, "file descriptors"),
            (self._memory_limit_for_priority(priority), stat.memory, "memory"),
        )
        for limit, value, name in checks:
            if limit is not None and value > limit:
                raise LimitExceeded(f"{name} limit exceeded: {value} > {limit}")

    def _memory_limit_for_priority(self, priority: int) -> int | None:
        if self.memory is None:
            return None
        priority = max(0, min(priority, RESERVATION_PRIORITY_ALWAYS))
        fraction = (1 + priority) / 256
        return max(1, int(self.memory * fraction))


ScopeCallback: TypeAlias = Callable[["ResourceScope"], None]


class ResourceScope:
    def __init__(
        self,
        name: str,
        limits: ResourceLimits | None = None,
        parents: tuple["ResourceScope", ...] = (),
    ) -> None:
        self.name = name
        self.limits = limits or ResourceLimits()
        self.parents = parents
        self._stat = ScopeStat()
        self._done = False

    def reserve_memory(
        self, size: int, priority: int = RESERVATION_PRIORITY_ALWAYS
    ) -> None:
        if size < 0:
            raise ValueError("size must be non-negative")
        self._reserve(ScopeStat(memory=size), priority=priority)

    def release_memory(self, size: int) -> None:
        if size < 0:
            raise ValueError("size must be non-negative")
        releasable = min(size, self._stat.memory)
        self._release(ScopeStat(memory=releasable))

    def stat(self) -> ScopeStat:
        return self._stat

    def begin_span(self) -> "ResourceScope":
        return ResourceScope(
            f"{self.name}.span",
            limits=ResourceLimits(),
            parents=(self,),
        )

    def done(self) -> None:
        if self._done:
            return
        self._release(self._stat)
        self._done = True

    def _reserve_conn(self, direction: Direction, use_fd: bool) -> None:
        stat = ScopeStat(
            num_conns_inbound=1 if direction is Direction.INBOUND else 0,
            num_conns_outbound=1 if direction is Direction.OUTBOUND else 0,
            num_fd=1 if use_fd else 0,
        )
        self._reserve(stat, priority=RESERVATION_PRIORITY_ALWAYS)

    def _reserve_stream(self, direction: Direction) -> None:
        stat = ScopeStat(
            num_streams_inbound=1 if direction is Direction.INBOUND else 0,
            num_streams_outbound=1 if direction is Direction.OUTBOUND else 0,
        )
        self._reserve(stat, priority=RESERVATION_PRIORITY_ALWAYS)

    def _reserve(self, stat: ScopeStat, *, priority: int) -> None:
        touched = self._walk_unique()
        previous = {scope: scope._stat for scope in touched}
        try:
            for scope in touched:
                next_stat = scope._stat.plus(stat)
                scope.limits.check(next_stat, priority=priority)
            for scope in touched:
                scope._stat = scope._stat.plus(stat)
        except Exception:
            for scope, old_stat in previous.items():
                scope._stat = old_stat
            raise

    def _release(self, stat: ScopeStat) -> None:
        for scope in self._walk_unique():
            scope._stat = scope._stat.minus(stat)

    def _add_parent(self, parent: "ResourceScope") -> None:
        if parent in self.parents:
            return
        existing_ids = {id(scope) for scope in self._walk_unique()}
        prospective = tuple(
            scope for scope in parent._walk_unique() if id(scope) not in existing_ids
        )
        previous = {scope: scope._stat for scope in prospective}
        try:
            for scope in prospective:
                next_stat = scope._stat.plus(self._stat)
                scope.limits.check(
                    next_stat, priority=RESERVATION_PRIORITY_ALWAYS
                )
            for scope in prospective:
                scope._stat = scope._stat.plus(self._stat)
        except Exception:
            for scope, old_stat in previous.items():
                scope._stat = old_stat
            raise
        self.parents = (*self.parents, parent)

    def _remove_parent(self, parent: "ResourceScope") -> None:
        if parent not in self.parents:
            return
        next_parents = tuple(scope for scope in self.parents if scope is not parent)
        still_reached_ids: set[int] = {id(self)}
        for next_parent in next_parents:
            still_reached_ids.update(id(scope) for scope in next_parent._walk_unique())
        for scope in parent._walk_unique():
            if id(scope) in still_reached_ids:
                continue
            scope._stat = scope._stat.minus(self._stat)
        self.parents = next_parents

    def _walk_unique(self) -> tuple["ResourceScope", ...]:
        scopes: list[ResourceScope] = []
        seen: set[int] = set()

        def visit(scope: ResourceScope) -> None:
            scope_id = id(scope)
            if scope_id in seen:
                return
            seen.add(scope_id)
            scopes.append(scope)
            for parent in scope.parents:
                visit(parent)

        visit(self)
        return tuple(scopes)


class PeerScope(ResourceScope):
    def __init__(self, peer_id: ID, limits: ResourceLimits, parent: ResourceScope):
        super().__init__(f"peer:{peer_id}", limits, parents=(parent,))
        self.peer_id = peer_id


class ProtocolScope(ResourceScope):
    def __init__(
        self, protocol_id: TProtocol, limits: ResourceLimits, parent: ResourceScope
    ):
        super().__init__(f"protocol:{protocol_id}", limits, parents=(parent,))
        self.protocol_id = protocol_id


class ServiceScope(ResourceScope):
    def __init__(self, service: str, limits: ResourceLimits, parent: ResourceScope):
        super().__init__(f"service:{service}", limits, parents=(parent,))
        self.service = service


class ConnManagementScope(ResourceScope):
    def __init__(
        self,
        name: str,
        direction: Direction,
        use_fd: bool,
        endpoint: Multiaddr | None,
        transient: ResourceScope,
        manager: "ResourceManager",
    ):
        super().__init__(name, ResourceLimits(), parents=(transient,))
        self.direction = direction
        self.use_fd = use_fd
        self.endpoint = endpoint
        self._transient = transient
        self._manager = manager
        self._peer_scope: PeerScope | None = None
        self._reserve_conn(direction, use_fd)

    def peer_scope(self) -> PeerScope | None:
        return self._peer_scope

    def set_peer(self, peer_id: ID) -> None:
        if self._peer_scope is not None and self._peer_scope.peer_id == peer_id:
            return
        peer_scope = self._manager.get_peer_scope(peer_id)
        self._add_parent(peer_scope)
        self._remove_parent(self._transient)
        self._peer_scope = peer_scope


class StreamManagementScope(ResourceScope):
    def __init__(
        self,
        name: str,
        direction: Direction,
        peer_scope: PeerScope,
        transient: ResourceScope,
        manager: "ResourceManager",
    ):
        super().__init__(name, ResourceLimits(), parents=(peer_scope, transient))
        self.direction = direction
        self._transient = transient
        self._manager = manager
        self._peer_scope = peer_scope
        self._protocol_scope: ProtocolScope | None = None
        self._service_scope: ServiceScope | None = None
        self._reserve_stream(direction)

    def peer_scope(self) -> PeerScope:
        return self._peer_scope

    def protocol_scope(self) -> ProtocolScope | None:
        return self._protocol_scope

    def service_scope(self) -> ServiceScope | None:
        return self._service_scope

    def set_protocol(self, protocol_id: TProtocol) -> None:
        if (
            self._protocol_scope is not None
            and self._protocol_scope.protocol_id == protocol_id
        ):
            return
        if self._protocol_scope is not None:
            self._remove_parent(self._protocol_scope)
        protocol_scope = self._manager.get_protocol_scope(protocol_id)
        self._add_parent(protocol_scope)
        self._remove_parent(self._transient)
        self._protocol_scope = protocol_scope

    def set_service(self, service: str) -> None:
        if self._service_scope is not None and self._service_scope.service == service:
            return
        if self._service_scope is not None:
            self._remove_parent(self._service_scope)
        service_scope = self._manager.get_service_scope(service)
        self._add_parent(service_scope)
        self._service_scope = service_scope


@dataclass(frozen=True)
class ResourceManagerLimits:
    system: ResourceLimits = ResourceLimits()
    transient: ResourceLimits = ResourceLimits()
    service_default: ResourceLimits = ResourceLimits()
    protocol_default: ResourceLimits = ResourceLimits()
    peer_default: ResourceLimits = ResourceLimits()
    services: dict[str, ResourceLimits] | None = None
    protocols: dict[TProtocol, ResourceLimits] | None = None
    peers: dict[ID, ResourceLimits] | None = None
    allowlisted_peers: frozenset[ID] = frozenset()

    @classmethod
    def default(cls) -> "ResourceManagerLimits":
        return cls(
            system=ResourceLimits(
                streams=4096,
                streams_inbound=2048,
                streams_outbound=2048,
                conns=1024,
                conns_inbound=512,
                conns_outbound=512,
                fd=1024,
                memory=1 << 30,
            ),
            transient=ResourceLimits(
                streams=1024,
                streams_inbound=512,
                streams_outbound=512,
                conns=256,
                conns_inbound=128,
                conns_outbound=128,
                fd=256,
                memory=256 << 20,
            ),
            service_default=ResourceLimits(streams=1024, memory=256 << 20),
            protocol_default=ResourceLimits(streams=1024, memory=256 << 20),
            peer_default=ResourceLimits(
                streams=256,
                streams_inbound=128,
                streams_outbound=128,
                conns=16,
                conns_inbound=8,
                conns_outbound=8,
                fd=16,
                memory=64 << 20,
            ),
        )

    @classmethod
    def autoscaled(cls, factor: float) -> "ResourceManagerLimits":
        defaults = cls.default()
        return cls(
            system=defaults.system.scale(factor),
            transient=defaults.transient.scale(factor),
            service_default=defaults.service_default.scale(factor),
            protocol_default=defaults.protocol_default.scale(factor),
            peer_default=defaults.peer_default.scale(factor),
        )

    @classmethod
    def from_config(cls, config: Mapping[str, Any]) -> "ResourceManagerLimits":
        base = (
            cls.autoscaled(float(config["autoscale"]))
            if "autoscale" in config
            else cls()
        )
        return cls(
            system=_limit_from_config(config, "system", base.system),
            transient=_limit_from_config(config, "transient", base.transient),
            service_default=_limit_from_config(
                config, "service_default", base.service_default
            ),
            protocol_default=_limit_from_config(
                config, "protocol_default", base.protocol_default
            ),
            peer_default=_limit_from_config(config, "peer_default", base.peer_default),
            services=_limits_map_from_config(
                config, "services", key_parser=str, defaults=base.services
            ),
            protocols=_limits_map_from_config(
                config, "protocols", key_parser=TProtocol, defaults=base.protocols
            ),
            peers=_limits_map_from_config(
                config, "peers", key_parser=_peer_id_from_config, defaults=base.peers
            ),
            allowlisted_peers=frozenset(
                _peer_id_from_config(peer_id)
                for peer_id in config.get(
                    "allowlisted_peers", base.allowlisted_peers
                )
            ),
        )


def _limit_from_config(
    config: Mapping[str, Any], key: str, default: ResourceLimits
) -> ResourceLimits:
    if key not in config:
        return default
    value = config[key]
    if not isinstance(value, Mapping):
        raise TypeError(f"{key} limits must be a mapping")
    return ResourceLimits.from_config(value)


def _limits_map_from_config(
    config: Mapping[str, Any],
    key: str,
    *,
    key_parser: Callable[[Any], TKey],
    defaults: dict[TKey, ResourceLimits] | None,
) -> dict[TKey, ResourceLimits] | None:
    if key not in config:
        return defaults
    value = config[key]
    if not isinstance(value, Mapping):
        raise TypeError(f"{key} limits must be a mapping")
    return {
        key_parser(item_key): ResourceLimits.from_config(item_limits)
        for item_key, item_limits in value.items()
    }


def _peer_id_from_config(peer_id: Any) -> ID:
    if isinstance(peer_id, ID):
        return peer_id
    if isinstance(peer_id, bytes):
        return ID(peer_id)
    if isinstance(peer_id, str):
        return ID.from_base58(peer_id)
    raise TypeError("peer id must be an ID, bytes, or base58 string")


class ResourceManager:
    def __init__(self, limits: ResourceManagerLimits | None = None) -> None:
        self.limits = limits or ResourceManagerLimits()
        self.system = ResourceScope("system", self.limits.system)
        self.transient = ResourceScope(
            "transient", self.limits.transient, parents=(self.system,)
        )
        self._services: dict[str, ServiceScope] = {}
        self._protocols: dict[TProtocol, ProtocolScope] = {}
        self._peers: dict[ID, PeerScope] = {}
        self._next_conn_id = 0
        self._next_stream_id = 0

    def view_system(self, callback: ScopeCallback) -> None:
        callback(self.system)

    def view_transient(self, callback: ScopeCallback) -> None:
        callback(self.transient)

    def view_service(self, service: str, callback: ScopeCallback) -> None:
        callback(self.get_service_scope(service))

    def view_protocol(self, protocol_id: TProtocol, callback: ScopeCallback) -> None:
        callback(self.get_protocol_scope(protocol_id))

    def view_peer(self, peer_id: ID, callback: ScopeCallback) -> None:
        callback(self.get_peer_scope(peer_id))

    def get_service_scope(self, service: str) -> ServiceScope:
        if service not in self._services:
            limits = (self.limits.services or {}).get(
                service, self.limits.service_default
            )
            self._services[service] = ServiceScope(service, limits, self.system)
        return self._services[service]

    def get_protocol_scope(self, protocol_id: TProtocol) -> ProtocolScope:
        if protocol_id not in self._protocols:
            limits = (self.limits.protocols or {}).get(
                protocol_id, self.limits.protocol_default
            )
            self._protocols[protocol_id] = ProtocolScope(
                protocol_id, limits, self.system
            )
        return self._protocols[protocol_id]

    def get_peer_scope(self, peer_id: ID) -> PeerScope:
        if peer_id not in self._peers:
            limits = (
                ResourceLimits()
                if peer_id in self.limits.allowlisted_peers
                else (self.limits.peers or {}).get(peer_id, self.limits.peer_default)
            )
            self._peers[peer_id] = PeerScope(peer_id, limits, self.system)
        return self._peers[peer_id]

    def open_connection(
        self,
        direction: Direction,
        *,
        use_fd: bool,
        endpoint: Multiaddr | None = None,
    ) -> ConnManagementScope:
        self._next_conn_id += 1
        return ConnManagementScope(
            f"conn:{self._next_conn_id}",
            direction,
            use_fd,
            endpoint,
            self.transient,
            self,
        )

    def open_stream(
        self, peer_id: ID, direction: Direction
    ) -> StreamManagementScope:
        self._next_stream_id += 1
        return StreamManagementScope(
            f"stream:{self._next_stream_id}",
            direction,
            self.get_peer_scope(peer_id),
            self.transient,
            self,
        )

    def close(self) -> None:
        self.system.done()
        self.transient.done()
        for scope in tuple(self._services.values()):
            scope.done()
        for scope in tuple(self._protocols.values()):
            scope.done()
        for scope in tuple(self._peers.values()):
            scope.done()


class NullScope(ResourceScope):
    def __init__(self) -> None:
        super().__init__("null")

    def reserve_memory(
        self, size: int, priority: int = RESERVATION_PRIORITY_ALWAYS
    ) -> None:
        return None

    def release_memory(self, size: int) -> None:
        return None

    def begin_span(self) -> "NullScope":
        return NullScope()

    def done(self) -> None:
        return None

    def peer_scope(self) -> "NullScope":
        return self

    def set_peer(self, peer_id: ID) -> None:
        return None

    def protocol_scope(self) -> "NullScope":
        return self

    def set_protocol(self, protocol_id: TProtocol) -> None:
        return None

    def service_scope(self) -> "NullScope":
        return self

    def set_service(self, service: str) -> None:
        return None


class NullResourceManager:
    def __init__(self) -> None:
        self.scope = NullScope()

    def view_system(self, callback: ScopeCallback) -> None:
        callback(self.scope)

    def view_transient(self, callback: ScopeCallback) -> None:
        callback(self.scope)

    def view_service(self, service: str, callback: ScopeCallback) -> None:
        callback(self.scope)

    def view_protocol(self, protocol_id: TProtocol, callback: ScopeCallback) -> None:
        callback(self.scope)

    def view_peer(self, peer_id: ID, callback: ScopeCallback) -> None:
        callback(self.scope)

    def open_connection(
        self,
        direction: Direction,
        *,
        use_fd: bool,
        endpoint: Multiaddr | None = None,
    ) -> NullScope:
        return NullScope()

    def open_stream(self, peer_id: ID, direction: Direction) -> NullScope:
        return NullScope()

    def close(self) -> None:
        return None
