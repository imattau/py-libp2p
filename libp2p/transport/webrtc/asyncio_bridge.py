"""Run an optional asyncio WebRTC engine behind a Trio-facing boundary."""

import asyncio
from collections.abc import Awaitable, Callable
import threading
from typing import Any, TypeVar

import trio

T = TypeVar("T")


class AsyncioLoopThread:
    """Own an asyncio loop in a worker thread and await work from Trio."""

    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._ready = threading.Event()
        self._thread: threading.Thread | None = None

    async def start(self) -> None:
        if self._thread is not None:
            return

        def run() -> None:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            self._loop = loop
            self._ready.set()
            loop.run_forever()
            loop.run_until_complete(loop.shutdown_asyncgens())
            loop.close()

        self._thread = threading.Thread(target=run, name="libp2p-webrtc", daemon=True)
        self._thread.start()
        await trio.to_thread.run_sync(self._ready.wait)

    async def call(
        self, operation: Callable[..., T], *args: Any, **kwargs: Any
    ) -> T:
        if self._loop is None:
            raise RuntimeError("asyncio WebRTC loop is not running")

        async def invoke() -> T:
            result = operation(*args, **kwargs)
            if isinstance(result, Awaitable):
                return await result
            return result

        future = asyncio.run_coroutine_threadsafe(invoke(), self._loop)
        return await trio.to_thread.run_sync(future.result)

    async def close(self) -> None:
        loop = self._loop
        thread = self._thread
        if loop is None or thread is None:
            return
        loop.call_soon_threadsafe(loop.stop)
        await trio.to_thread.run_sync(thread.join)
        self._loop = None
        self._thread = None
