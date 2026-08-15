from dataclasses import dataclass

QUIC_V1_MULTIADDR_PROTOCOL = "quic-v1"


@dataclass(frozen=True)
class QuicTransportConfig:
    """Limits and timeouts shared by the Trio QUIC transport layers."""

    idle_timeout: float = 30.0
    handshake_timeout: float = 10.0
    max_datagram_size: int = 1200
    max_incoming_streams: int = 100
    max_outgoing_streams: int = 100

    def __post_init__(self) -> None:
        if self.idle_timeout <= 0:
            raise ValueError("idle_timeout must be positive")
        if self.handshake_timeout <= 0:
            raise ValueError("handshake_timeout must be positive")
        if self.max_datagram_size < 1200:
            raise ValueError("max_datagram_size must be at least 1200 bytes")
        if self.max_incoming_streams < 1:
            raise ValueError("max_incoming_streams must be positive")
        if self.max_outgoing_streams < 1:
            raise ValueError("max_outgoing_streams must be positive")
