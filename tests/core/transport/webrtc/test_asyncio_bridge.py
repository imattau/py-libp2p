import asyncio

import pytest

from libp2p.transport.webrtc.asyncio_bridge import AsyncioLoopThread


@pytest.mark.trio
async def test_asyncio_loop_thread_calls_and_closes() -> None:
    bridge = AsyncioLoopThread()
    await bridge.start()
    try:
        result = await bridge.call(asyncio.sleep, 0, result="ready")
        assert result == "ready"
    finally:
        await bridge.close()
