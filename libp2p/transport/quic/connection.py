from collections.abc import Sequence
from typing import Any

from .config import QuicTransportConfig

LIBP2P_QUIC_ALPN = "libp2p"


def create_quic_connection(
    *,
    is_client: bool,
    config: QuicTransportConfig | None = None,
    alpn_protocols: Sequence[str] = (LIBP2P_QUIC_ALPN,),
) -> Any:
    """Create an aioquic connection configured for the libp2p QUIC profile."""
    try:
        from aioquic.quic.configuration import QuicConfiguration
        from aioquic.quic.connection import QuicConnection
    except ImportError as error:
        raise RuntimeError(
            "aioquic is required for the native QUIC transport"
        ) from error

    transport_config = config or QuicTransportConfig()
    aioquic_config = QuicConfiguration(
        is_client=is_client,
        alpn_protocols=list(alpn_protocols),
    )
    aioquic_config.idle_timeout = transport_config.idle_timeout
    aioquic_config.max_datagram_size = transport_config.max_datagram_size
    return QuicConnection(configuration=aioquic_config)
