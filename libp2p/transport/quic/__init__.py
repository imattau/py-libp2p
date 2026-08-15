"""Configuration primitives for the native Trio QUIC transport."""

from .config import (
    QUIC_V1_MULTIADDR_PROTOCOL,
    QuicTransportConfig,
)

__all__ = (
    "QUIC_V1_MULTIADDR_PROTOCOL",
    "QuicTransportConfig",
)
