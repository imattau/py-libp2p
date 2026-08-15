"""Shared WebRTC transport framing primitives."""

from .framing import (
    MAX_MESSAGE_SIZE,
    WebRTCFrame,
    decode_frames,
    encode_frame,
)
from .asyncio_bridge import AsyncioLoopThread
from .connection import WebRTCConnection

__all__ = [
    "AsyncioLoopThread",
    "MAX_MESSAGE_SIZE",
    "WebRTCConnection",
    "WebRTCFrame",
    "decode_frames",
    "encode_frame",
]
