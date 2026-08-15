"""Configuration primitives for the native Trio QUIC transport."""

from .config import (
    QUIC_V1_MULTIADDR_PROTOCOL,
    QuicTransportConfig,
)
from .connection import (
    LIBP2P_QUIC_ALPN,
    LIBP2P_PUBLIC_KEY_EXTENSION,
    create_libp2p_certificate,
    create_quic_connection,
)
from .driver import QuicTrioDriver
from .events import (
    QuicConnectionClosed,
    QuicHandshakeComplete,
    QuicStreamData,
)
from .stream import QuicStream
from .stream_manager import QuicStreamManager

__all__ = (
    "QUIC_V1_MULTIADDR_PROTOCOL",
    "LIBP2P_QUIC_ALPN",
    "LIBP2P_PUBLIC_KEY_EXTENSION",
    "QuicTransportConfig",
    "QuicTrioDriver",
    "QuicConnectionClosed",
    "QuicHandshakeComplete",
    "QuicStreamData",
    "QuicStream",
    "QuicStreamManager",
    "create_libp2p_certificate",
    "create_quic_connection",
)
