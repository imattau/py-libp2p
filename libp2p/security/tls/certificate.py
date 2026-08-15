from datetime import datetime, timedelta, timezone
from typing import Any

from cryptography import x509
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import (
    dsa,
    ec,
    padding,
    rsa,
)
from cryptography.x509.oid import NameOID, ObjectIdentifier

from libp2p.crypto.keys import KeyPair
from libp2p.crypto.serialization import deserialize_public_key
from libp2p.peer.id import ID

LIBP2P_PUBLIC_KEY_EXTENSION = ObjectIdentifier("1.3.6.1.4.1.53594.1.1")
LIBP2P_TLS_HANDSHAKE_PREFIX = b"libp2p-tls-handshake:"
LIBP2P_CERTIFICATE_VALIDITY = timedelta(days=365 * 100)


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
    if offset + 1 >= len(data) or data[offset] != 0x04:
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
    now = datetime.now(timezone.utc)
    not_valid_before = getattr(certificate, "not_valid_before_utc", None)
    not_valid_after = getattr(certificate, "not_valid_after_utc", None)
    if not_valid_before is None:
        not_valid_before = certificate.not_valid_before.replace(tzinfo=timezone.utc)
    if not_valid_after is None:
        not_valid_after = certificate.not_valid_after.replace(tzinfo=timezone.utc)
    if now < not_valid_before or now > not_valid_after:
        raise ValueError("libp2p TLS certificate is outside its validity period")

    public_key = certificate.public_key()
    try:
        if isinstance(public_key, ec.EllipticCurvePublicKey):
            public_key.verify(
                certificate.signature,
                certificate.tbs_certificate_bytes,
                ec.ECDSA(certificate.signature_hash_algorithm),
            )
        elif isinstance(public_key, rsa.RSAPublicKey):
            public_key.verify(
                certificate.signature,
                certificate.tbs_certificate_bytes,
                padding.PKCS1v15(),
                certificate.signature_hash_algorithm,
            )
        elif isinstance(public_key, dsa.DSAPublicKey):
            public_key.verify(
                certificate.signature,
                certificate.tbs_certificate_bytes,
                certificate.signature_hash_algorithm,
            )
        else:
            raise ValueError("unsupported libp2p TLS certificate key type")
    except InvalidSignature as error:
        raise ValueError("invalid libp2p TLS certificate signature") from error

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
    name = x509.Name([x509.NameAttribute(NameOID.ORGANIZATION_NAME, "libp2p.io")])
    certificate = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(certificate_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + LIBP2P_CERTIFICATE_VALIDITY)
        .add_extension(
            x509.UnrecognizedExtension(LIBP2P_PUBLIC_KEY_EXTENSION, extension),
            critical=True,
        )
        .sign(certificate_key, hashes.SHA256())
    )
    return certificate, certificate_key
