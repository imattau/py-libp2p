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

__all__ = (
    "QUIC_V1_MULTIADDR_PROTOCOL",
    "LIBP2P_QUIC_ALPN",
    "LIBP2P_PUBLIC_KEY_EXTENSION",
    "QuicTransportConfig",
    "QuicTrioDriver",
    "create_libp2p_certificate",
    "create_quic_connection",
)
