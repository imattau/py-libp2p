"""Shared WebRTC transport framing primitives."""

from .framing import (
    MAX_MESSAGE_SIZE,
    WebRTCFrame,
    decode_frames,
    encode_frame,
)
from .asyncio_bridge import AsyncioLoopThread
from .aiortc_engine import (
    AiortcWebRTCEngine,
    SessionDescription,
    WebRTCDependencyError,
)
from .connection import WebRTCConnection
from .direct import WebRTCDirectAddress

__all__ = [
    "AsyncioLoopThread",
    "AiortcWebRTCEngine",
    "MAX_MESSAGE_SIZE",
    "WebRTCConnection",
    "WebRTCDirectAddress",
    "WebRTCDependencyError",
    "WebRTCFrame",
    "SessionDescription",
    "decode_frames",
    "encode_frame",
]
