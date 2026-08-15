import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import Encoding

from libp2p.crypto.ed25519 import create_new_key_pair
from libp2p.transport.quic.config import QuicTransportConfig
from libp2p.transport.quic.connection import (
    LIBP2P_PUBLIC_KEY_EXTENSION,
    LIBP2P_TLS_HANDSHAKE_PREFIX,
    create_libp2p_certificate,
    create_quic_connection,
    peer_id_from_certificate,
)


def _read_octet_string(data: bytes, offset: int) -> tuple[bytes, int]:
    assert data[offset] == 0x04
    length = data[offset + 1]
    offset += 2
    if length & 0x80:
        size = length & 0x7F
        length = int.from_bytes(data[offset : offset + size], "big")
        offset += size
    return data[offset : offset + length], offset + length


def test_create_libp2p_certificate_carries_signed_host_key():
    key_pair = create_new_key_pair(seed=b"p" * 32)
    certificate, certificate_key = create_libp2p_certificate(key_pair)
    extension = certificate.extensions.get_extension_for_oid(
        LIBP2P_PUBLIC_KEY_EXTENSION
    )

    assert extension.critical
    assert certificate.issuer == certificate.subject
    assert isinstance(certificate_key, ec.EllipticCurvePrivateKey)
    assert certificate.public_bytes(Encoding.DER)

    signed_key = extension.value.value
    assert signed_key.startswith(b"\x30")
    sequence_length = signed_key[1]
    sequence_offset = 2
    if sequence_length & 0x80:
        sequence_offset += sequence_length & 0x7F
    public_key, offset = _read_octet_string(signed_key, sequence_offset)
    signature, offset = _read_octet_string(signed_key, offset)
    assert offset == len(signed_key)
    assert public_key == key_pair.public_key.serialize()
    assert key_pair.public_key.verify(
        LIBP2P_TLS_HANDSHAKE_PREFIX + key_pair.public_key.serialize(),
        signature,
    )


def test_create_quic_connection_configures_identity():
    key_pair = create_new_key_pair(seed=b"q" * 32)
    connection = create_quic_connection(
        is_client=True,
        key_pair=key_pair,
        config=QuicTransportConfig(idle_timeout=7.5, max_datagram_size=1400),
    )

    assert connection.configuration.is_client
    assert connection.configuration.alpn_protocols == ["libp2p"]
    assert connection.configuration.idle_timeout == 7.5
    assert connection.configuration.max_datagram_size == 1400
    assert isinstance(connection.configuration.certificate, x509.Certificate)
    assert connection.configuration.private_key is not None


def test_peer_id_from_certificate_rejects_tampered_signature():
    certificate, certificate_key = create_libp2p_certificate(
        create_new_key_pair(seed=b"t" * 32)
    )
    extension = certificate.extensions.get_extension_for_oid(
        LIBP2P_PUBLIC_KEY_EXTENSION
    )
    tampered = bytearray(extension.value.value)
    tampered[-1] ^= 1
    builder = (
        x509.CertificateBuilder()
        .subject_name(certificate.subject)
        .issuer_name(certificate.issuer)
        .public_key(certificate.public_key())
        .serial_number(certificate.serial_number)
        .not_valid_before(certificate.not_valid_before_utc)
        .not_valid_after(certificate.not_valid_after_utc)
        .add_extension(
            x509.UnrecognizedExtension(LIBP2P_PUBLIC_KEY_EXTENSION, bytes(tampered)),
            critical=True,
        )
    )
    tampered_certificate = builder.sign(certificate_key, hashes.SHA256())

    with pytest.raises(ValueError, match="identity signature"):
        peer_id_from_certificate(tampered_certificate)
