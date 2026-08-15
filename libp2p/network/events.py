from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from typing import Generic, TypeVar

from multiaddr import Multiaddr
import trio

from libp2p.abc import (
    INetConn,
    INetStream,
)


@dataclass(frozen=True)
class EventConnected:
    conn: INetConn


@dataclass(frozen=True)
class EventDisconnected:
    conn: INetConn


@dataclass(frozen=True)
class EventOpenedStream:
    stream: INetStream


@dataclass(frozen=True)
class EventClosedStream:
    stream: INetStream


@dataclass(frozen=True)
class EventListen:
    multiaddr: Multiaddr


@dataclass(frozen=True)
class EventListenClose:
    multiaddr: Multiaddr


NetworkEvent = (
    EventConnected
    | EventDisconnected
    | EventOpenedStream
    | EventClosedStream
    | EventListen
    | EventListenClose
)

TEvent = TypeVar("TEvent", bound=NetworkEvent)


class EventSubscription(Generic[TEvent]):
    def __init__(
        self,
        event_type: type[TEvent] | None,
        receive_channel: trio.MemoryReceiveChannel[TEvent],
        unsubscribe: Callable[[], None],
    ) -> None:
        self.event_type = event_type
        self._receive_channel = receive_channel
        self._unsubscribe = unsubscribe

    async def receive(self) -> TEvent:
        return await self._receive_channel.receive()

    async def unsubscribe(self) -> None:
        self._unsubscribe()
        await self._receive_channel.aclose()

    def __aiter__(self) -> AsyncIterator[TEvent]:
        return self

    async def __anext__(self) -> TEvent:
        try:
            return await self.receive()
        except trio.EndOfChannel as error:
            raise StopAsyncIteration from error


@dataclass(frozen=True)
class _Subscriber:
    event_type: type[NetworkEvent] | None
    send_channel: trio.MemorySendChannel[NetworkEvent]


class EventBus:
    def __init__(self) -> None:
        self._subscribers: list[_Subscriber] = []
        self._lock = trio.Lock()

    async def publish(self, event: NetworkEvent) -> None:
        async with self._lock:
            subscribers = tuple(self._subscribers)

        for subscriber in subscribers:
            if subscriber.event_type is not None and not isinstance(
                event, subscriber.event_type
            ):
                continue
            try:
                await subscriber.send_channel.send(event)
            except trio.BrokenResourceError:
                await self._remove_subscriber(subscriber)

    async def subscribe(
        self,
        event_type: type[TEvent] | None = None,
        *,
        max_buffer_size: int = 16,
    ) -> EventSubscription[TEvent]:
        send_channel, receive_channel = trio.open_memory_channel[NetworkEvent](
            max_buffer_size
        )
        subscriber = _Subscriber(event_type, send_channel)
        async with self._lock:
            self._subscribers.append(subscriber)

        def unsubscribe() -> None:
            send_channel.close()
            if subscriber in self._subscribers:
                self._subscribers.remove(subscriber)

        return EventSubscription(event_type, receive_channel, unsubscribe)

    async def _remove_subscriber(self, subscriber: _Subscriber) -> None:
        async with self._lock:
            if subscriber in self._subscribers:
                self._subscribers.remove(subscriber)


__all__ = (
    "EventBus",
    "EventClosedStream",
    "EventConnected",
    "EventDisconnected",
    "EventListen",
    "EventListenClose",
    "EventOpenedStream",
    "EventSubscription",
    "NetworkEvent",
)
