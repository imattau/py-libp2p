from dataclasses import dataclass

from cryptography import x509
from cryptography.hazmat.primitives.serialization import Encoding

from libp2p.crypto.keys import KeyPair
from libp2p.peer.id import ID

from .certificate import (
    create_libp2p_certificate,
    peer_id_from_certificate,
)


@dataclass(frozen=True)
class TLSIdentity:
    """Certificate identity used by the libp2p TLS handshake."""

    key_pair: KeyPair
    certificate: x509.Certificate
    certificate_key: object

    @classmethod
    def create(cls, key_pair: KeyPair) -> "TLSIdentity":
        certificate, certificate_key = create_libp2p_certificate(key_pair)
        return cls(key_pair, certificate, certificate_key)

    @property
    def peer_id(self) -> ID:
        return ID.from_pubkey(self.key_pair.public_key)

    @property
    def certificate_der(self) -> bytes:
        return self.certificate.public_bytes(Encoding.DER)

    def verify_peer_certificate(self, certificate: x509.Certificate) -> ID:
        return peer_id_from_certificate(certificate)
