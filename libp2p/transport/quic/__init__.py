"""Configuration primitives for the native Trio QUIC transport."""

from .config import (
    QUIC_V1_MULTIADDR_PROTOCOL,
    QuicTransportConfig,
)
from .driver import QuicTrioDriver

__all__ = (
    "QUIC_V1_MULTIADDR_PROTOCOL",
    "QuicTransportConfig",
    "QuicTrioDriver",
)
