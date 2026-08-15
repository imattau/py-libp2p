from __future__ import annotations

from collections import deque
from typing import Protocol

import trio
from trio_websocket import ConnectionClosed

from libp2p.abc import IRawConnection


class WebSocketLike(Protocol):
    async def get_message(self) -> str | bytes: ...

    async def send_message(self, message: bytes) -> None: ...

    async def aclose(self) -> None: ...


class WebSocketConnection(IRawConnection):
    """Adapt binary WebSocket messages to libp2p's byte-stream contract."""

    def __init__(
        self,
        websocket: WebSocketLike,
        is_initiator: bool,
        close_signal: trio.Event | None = None,
    ) -> None:
        self.websocket = websocket
        self.is_initiator = is_initiator
        self._close_signal = close_signal
        self._buffer: deque[bytes] = deque()
        self._closed = False

    async def read(self, n: int | None = None) -> bytes:
        if self._closed and not self._buffer:
            return b""
        while not self._buffer:
            try:
                message = await self.websocket.get_message()
            except ConnectionClosed:
                self._closed = True
                return b""
            if isinstance(message, str):
                raise ValueError("libp2p WebSocket transport requires binary messages")
            if message:
                self._buffer.append(message)
            else:
                self._closed = True
                return b""

        data = self._buffer.popleft()
        if n is not None and len(data) > n:
            self._buffer.appendleft(data[n:])
            return data[:n]
        return data

    async def write(self, data: bytes) -> None:
        if self._closed:
            raise RuntimeError("WebSocket connection is closed")
        if data:
            await self.websocket.send_message(data)

    async def close(self) -> None:
        if not self._closed:
            self._closed = True
            if self._close_signal is not None:
                self._close_signal.set()
            else:
                await self.websocket.aclose()

    def get_remote_address(self) -> tuple[str, int] | None:
        return None
