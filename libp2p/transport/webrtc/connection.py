"""Adapt an asyncio WebRTC data channel to the Trio byte-stream contract."""

from collections import deque
from typing import Any, Protocol

import trio

from libp2p.abc import IRawConnection

from .framing import MAX_MESSAGE_SIZE, WebRTCFrame, decode_frames, encode_frame


class DataChannel(Protocol):
    def send(self, data: bytes) -> None: ...

    def close(self) -> None: ...

    def on(self, event: str, handler: Any) -> None: ...


class WebRTCConnection(IRawConnection):
    """Trio-facing connection over a reliable WebRTC data channel."""

    def __init__(
        self,
        channel: DataChannel,
        engine_call: Any,
        *,
        is_initiator: bool,
    ) -> None:
        self.channel = channel
        self.engine_call = engine_call
        self.is_initiator = is_initiator
        self._trio_token = trio.lowlevel.current_trio_token()
        self._incoming_send, self._incoming_receive = trio.open_memory_channel[bytes](
            32
        )
        self._buffer = bytearray()
        self._messages: deque[bytes] = deque()
        self._read_closed = False
        self._write_closed = False
        self._closed = False
        self._ready = trio.Event()
        if getattr(channel, "readyState", "open") == "open":
            self._ready.set()

    def on_open(self) -> None:
        """Receive the aiortc data-channel open callback."""
        trio.from_thread.run_sync(self._mark_ready, trio_token=self._trio_token)

    def on_close(self) -> None:
        """Receive the aiortc data-channel close callback."""
        trio.from_thread.run(
            self._finish_remote_close,
            trio_token=self._trio_token,
        )

    async def wait_ready(self) -> None:
        """Wait until the underlying data channel is ready for writes."""
        await self._ready.wait()
        if self._closed:
            raise RuntimeError("WebRTC connection is closed")

    def _mark_ready(self) -> None:
        self._ready.set()

    async def _finish_remote_close(self) -> None:
        self._read_closed = True
        self._write_closed = True
        await self._incoming_send.aclose()

    def on_message(self, message: bytes | str) -> None:
        """Receive a data-channel callback from the asyncio engine thread."""
        if isinstance(message, str):
            raise ValueError("libp2p WebRTC data channels require binary messages")
        trio.from_thread.run(
            self.feed_message,
            message,
            trio_token=self._trio_token,
        )

    async def feed_message(self, message: bytes) -> None:
        """Inject one binary data-channel message from a Trio test or bridge."""
        await self._incoming_send.send(message)

    async def read(self, n: int | None = None) -> bytes:
        while not self._messages and not self._read_closed:
            try:
                incoming = await self._incoming_receive.receive()
            except trio.EndOfChannel:
                self._read_closed = True
                break
            self._buffer.extend(incoming)
            frames, remainder = decode_frames(bytes(self._buffer))
            self._buffer = bytearray(remainder)
            for frame in frames:
                if frame.flag == 0:
                    self._read_closed = True
                elif frame.flag == 1:
                    self._write_closed = True
                elif frame.flag == 2:
                    raise ConnectionResetError("WebRTC stream reset by peer")
                elif frame.flag == 3:
                    self._write_closed = True
                elif frame.message:
                    self._messages.append(frame.message)
        if not self._messages:
            return b""
        message = self._messages.popleft()
        if n is not None and len(message) > n:
            self._messages.appendleft(message[n:])
            return message[:n]
        return message

    async def write(self, data: bytes) -> None:
        if self._closed or self._write_closed:
            raise RuntimeError("WebRTC connection is closed for writing")
        limit = MAX_MESSAGE_SIZE - 32
        for offset in range(0, len(data), limit):
            await self.engine_call(
                self.channel.send,
                encode_frame(WebRTCFrame(data[offset : offset + limit])),
            )

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if not self._write_closed:
            await self.engine_call(
                self.channel.send,
                encode_frame(WebRTCFrame(flag=0)),
            )
        await self.engine_call(self.channel.close)

    def get_remote_address(self) -> tuple[str, int] | None:
        return None
