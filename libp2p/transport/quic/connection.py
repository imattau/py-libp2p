from collections.abc import Sequence
import ssl
from typing import Any

from libp2p.crypto.keys import KeyPair
from libp2p.security.tls.certificate import (
    LIBP2P_PUBLIC_KEY_EXTENSION,
    LIBP2P_TLS_HANDSHAKE_PREFIX,
    create_libp2p_certificate,
    peer_id_from_certificate,
)

from .config import QuicTransportConfig

__all__ = [
    "LIBP2P_QUIC_ALPN",
    "LIBP2P_PUBLIC_KEY_EXTENSION",
    "LIBP2P_TLS_HANDSHAKE_PREFIX",
    "create_libp2p_certificate",
    "create_quic_connection",
    "peer_id_from_certificate",
]

LIBP2P_QUIC_ALPN = "libp2p"
def create_quic_connection(
    *,
    is_client: bool,
    key_pair: KeyPair | None = None,
    original_destination_connection_id: bytes | None = None,
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
    aioquic_config.verify_mode = ssl.CERT_NONE
    if key_pair is not None:
        certificate, certificate_key = create_libp2p_certificate(key_pair)
        aioquic_config.certificate = certificate
        aioquic_config.private_key = certificate_key
    connection_kwargs = {}
    if original_destination_connection_id is not None:
        connection_kwargs["original_destination_connection_id"] = (
            original_destination_connection_id
        )
    return QuicConnection(configuration=aioquic_config, **connection_kwargs)
