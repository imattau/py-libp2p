from collections.abc import Callable
from typing import (
    Any,
    Protocol,
)


class QuicConnectionBackend(Protocol):
    """Sans-I/O surface implemented by ``aioquic.QuicConnection``."""

    def datagrams_to_send(self, now: float) -> list[tuple[bytes, Any]]: ...

    def get_timer(self) -> float | None: ...

    def handle_timer(self, now: float) -> None: ...

    def next_event(self) -> Any | None: ...

    def receive_datagram(self, data: bytes, addr: Any, now: float) -> None: ...


async def flush_datagrams(
    connection: QuicConnectionBackend,
    send_datagram: Callable[[bytes, Any], Any],
    now: float,
) -> int:
    """Flush backend output through a Trio-owned datagram sender."""
    sent = 0
    for data, addr in connection.datagrams_to_send(now):
        result = send_datagram(data, addr)
        if hasattr(result, "__await__"):
            await result
        sent += 1
    return sent


def drain_events(
    connection: QuicConnectionBackend,
    handle_event: Callable[[Any], None],
) -> int:
    """Deliver all currently buffered backend events to the transport layer."""
    drained = 0
    while True:
        event = connection.next_event()
        if event is None:
            return drained
        handle_event(event)
        drained += 1
