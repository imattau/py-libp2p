import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    PublicFormat,
)
from cryptography.x509 import load_der_x509_certificate

from libp2p.crypto.ed25519 import create_new_key_pair
from libp2p.security.tls.certificate import LIBP2P_CERTIFICATE_VALIDITY
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
    assert (
        certificate.not_valid_after_utc - certificate.not_valid_before_utc
        >= LIBP2P_CERTIFICATE_VALIDITY
    )

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
        LIBP2P_TLS_HANDSHAKE_PREFIX
        + certificate_key.public_key().public_bytes(
            Encoding.DER, PublicFormat.SubjectPublicKeyInfo
        ),
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


def test_peer_id_from_certificate_rejects_invalid_certificate_signature():
    certificate, certificate_key = create_libp2p_certificate(
        create_new_key_pair(seed=b"s" * 32)
    )
    replacement_key = ec.generate_private_key(ec.SECP256R1())
    invalid_certificate = (
        x509.CertificateBuilder()
        .subject_name(certificate.subject)
        .issuer_name(certificate.issuer)
        .public_key(replacement_key.public_key())
        .serial_number(certificate.serial_number)
        .not_valid_before(certificate.not_valid_before_utc)
        .not_valid_after(certificate.not_valid_after_utc)
        .add_extension(
            certificate.extensions.get_extension_for_oid(
                LIBP2P_PUBLIC_KEY_EXTENSION
            ).value,
            critical=True,
        )
        .sign(certificate_key, hashes.SHA256())
    )

    with pytest.raises(ValueError, match="certificate signature"):
        peer_id_from_certificate(invalid_certificate)


def test_peer_id_from_certificate_rejects_truncated_signed_key():
    certificate, certificate_key = create_libp2p_certificate(
        create_new_key_pair(seed=b"r" * 32)
    )
    extension = certificate.extensions.get_extension_for_oid(
        LIBP2P_PUBLIC_KEY_EXTENSION
    )
    truncated = extension.value.value[:-1]
    malformed_certificate = (
        x509.CertificateBuilder()
        .subject_name(certificate.subject)
        .issuer_name(certificate.issuer)
        .public_key(certificate.public_key())
        .serial_number(certificate.serial_number)
        .not_valid_before(certificate.not_valid_before_utc)
        .not_valid_after(certificate.not_valid_after_utc)
        .add_extension(
            x509.UnrecognizedExtension(LIBP2P_PUBLIC_KEY_EXTENSION, truncated),
            critical=True,
        )
        .sign(certificate_key, hashes.SHA256())
    )

    with pytest.raises(ValueError, match="signed-key|public-key extension"):
        peer_id_from_certificate(malformed_certificate)


def test_peer_id_from_certificate_accepts_tls_spec_ed25519_vector():
    certificate_der = bytes.fromhex(
        "308201ae30820156a0030201020204499602d2300a06082a8648ce3d040302"
        "302031123010060355040a13096c69627032702e696f310a30080603550405"
        "1301313020170d3735303130313133303030305a180f343039363031303131"
        "33303030305a302031123010060355040a13096c69627032702e696f310a"
        "300806035504051301313059301306072a8648ce3d020106082a8648ce3d"
        "030107034200040c901d423c831ca85e27c73c263ba132721bb9d7a84c4f"
        "0380b2a6756fd601331c8870234dec878504c174144fa4b14b66a65169160"
        "6d8173e55bd37e381569ea37c307a3078060a2b0601040183a25a0101046a"
        "3068042408011220a77f1d92fedb59dddaea5a1c4abd1ac2fbde7d7b879ed"
        "364501809923d7c11b90440d90d2769db992d5e6195dbb08e706b6651e024f"
        "da6cfb8846694a435519941cac215a8207792e42849cccc6cd8136c6e4bde"
        "92a58c5e08cfd4206eb5fe0bf909300a06082a8648ce3d04030203460030"
        "43021f50f6b6c52711a881778718238f650c9fb48943ae6ee6d28427dc607"
        "1ae55e702203625f116a7a454db9c56986c82a25682f7248ea1cb764d322e"
        "a983ed36a31b77"
    )
    certificate = load_der_x509_certificate(certificate_der)

    assert str(peer_id_from_certificate(certificate)) == (
        "12D3KooWM6CgA9iBFZmcYAHA6A2qvbAxqfkmrYiRQuz3XEsk4Ksv"
    )
