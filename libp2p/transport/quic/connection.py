from collections.abc import Sequence
from datetime import (
    datetime,
    timedelta,
    timezone,
)
import ssl
from typing import Any

from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID, ObjectIdentifier

from libp2p.crypto.keys import KeyPair
from libp2p.crypto.serialization import deserialize_public_key
from libp2p.peer.id import ID

from .config import QuicTransportConfig

LIBP2P_QUIC_ALPN = "libp2p"
LIBP2P_PUBLIC_KEY_EXTENSION = ObjectIdentifier("1.3.6.1.4.1.53594.1.1")
LIBP2P_TLS_HANDSHAKE_PREFIX = b"libp2p-tls-handshake:"


def _der_length(length: int) -> bytes:
    if length < 0x80:
        return bytes((length,))
    encoded = length.to_bytes((length.bit_length() + 7) // 8, "big")
    return bytes((0x80 | len(encoded),)) + encoded


def _der_octet_string(value: bytes) -> bytes:
    return b"\x04" + _der_length(len(value)) + value


def _encode_signed_key(public_key: bytes, signature: bytes) -> bytes:
    body = _der_octet_string(public_key) + _der_octet_string(signature)
    return b"\x30" + _der_length(len(body)) + body


def _decode_der_octet_string(data: bytes, offset: int) -> tuple[bytes, int]:
    if offset >= len(data) or data[offset] != 0x04:
        raise ValueError("invalid libp2p TLS public-key extension")
    length = data[offset + 1]
    offset += 2
    if length & 0x80:
        size = length & 0x7F
        if size == 0 or offset + size > len(data):
            raise ValueError("invalid libp2p TLS public-key extension length")
        length = int.from_bytes(data[offset : offset + size], "big")
        offset += size
    end = offset + length
    if end > len(data):
        raise ValueError("truncated libp2p TLS public-key extension")
    return data[offset:end], end


def peer_id_from_certificate(certificate: x509.Certificate) -> ID:
    """Validate a libp2p TLS certificate and return its authenticated peer ID."""
    try:
        extension = certificate.extensions.get_extension_for_oid(
            LIBP2P_PUBLIC_KEY_EXTENSION
        )
    except x509.ExtensionNotFound as error:
        raise ValueError("libp2p TLS public-key extension is missing") from error

    signed_key = extension.value.value
    if len(signed_key) < 2 or signed_key[0] != 0x30:
        raise ValueError("invalid libp2p TLS signed-key sequence")
    sequence_length = signed_key[1]
    sequence_offset = 2
    if sequence_length & 0x80:
        size = sequence_length & 0x7F
        if size == 0 or sequence_offset + size > len(signed_key):
            raise ValueError("invalid libp2p TLS signed-key length")
        sequence_length = int.from_bytes(
            signed_key[sequence_offset : sequence_offset + size], "big"
        )
        sequence_offset += size
    sequence_end = sequence_offset + sequence_length
    if sequence_end != len(signed_key):
        raise ValueError("invalid libp2p TLS signed-key sequence length")
    public_key_bytes, offset = _decode_der_octet_string(signed_key, sequence_offset)
    signature, offset = _decode_der_octet_string(signed_key, offset)
    if offset != sequence_end:
        raise ValueError("invalid libp2p TLS signed-key fields")

    public_key = deserialize_public_key(public_key_bytes)
    handshake_data = LIBP2P_TLS_HANDSHAKE_PREFIX + public_key_bytes
    try:
        valid = public_key.verify(handshake_data, signature)
    except Exception as error:
        raise ValueError("invalid libp2p TLS identity signature") from error
    if not valid:
        raise ValueError("invalid libp2p TLS identity signature")
    return ID.from_pubkey(public_key)


def create_libp2p_certificate(key_pair: KeyPair) -> tuple[x509.Certificate, Any]:
    """Create a self-signed certificate carrying a libp2p host identity."""
    host_public_key = key_pair.public_key.serialize()
    handshake_data = LIBP2P_TLS_HANDSHAKE_PREFIX + host_public_key
    host_signature = key_pair.private_key.sign(handshake_data)
    extension = _encode_signed_key(host_public_key, host_signature)

    certificate_key = ec.generate_private_key(ec.SECP256R1())
    now = datetime.now(timezone.utc)
    name = x509.Name(
        [x509.NameAttribute(NameOID.ORGANIZATION_NAME, "libp2p.io")]
    )
    certificate = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(certificate_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(days=30))
        .add_extension(
            x509.UnrecognizedExtension(LIBP2P_PUBLIC_KEY_EXTENSION, extension),
            critical=True,
        )
        .sign(certificate_key, hashes.SHA256())
    )
    return certificate, certificate_key


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
