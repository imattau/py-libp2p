"""Libp2p TLS identity certificate helpers."""

from libp2p.custom_types import TProtocol

TLS_PROTOCOL_ID = TProtocol("/tls/1.0.0")

from .certificate import (
    LIBP2P_CERTIFICATE_VALIDITY,
    LIBP2P_PUBLIC_KEY_EXTENSION,
    LIBP2P_TLS_HANDSHAKE_PREFIX,
    create_libp2p_certificate,
    peer_id_from_certificate,
    public_key_from_certificate,
)
from .identity import TLSIdentity
from .context import create_tls_context
from .transport import TLSTransport

__all__ = [
    "LIBP2P_CERTIFICATE_VALIDITY",
    "TLS_PROTOCOL_ID",
    "LIBP2P_PUBLIC_KEY_EXTENSION",
    "LIBP2P_TLS_HANDSHAKE_PREFIX",
    "create_libp2p_certificate",
    "peer_id_from_certificate",
    "public_key_from_certificate",
    "TLSIdentity",
    "create_tls_context",
    "TLSTransport",
]
