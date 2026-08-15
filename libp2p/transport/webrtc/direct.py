"""WebRTC Direct multiaddress and certificate-hash handling."""

import base64
from dataclasses import dataclass
import hashlib

import base58

from libp2p.peer.id import ID


@dataclass(frozen=True)
class WebRTCDirectAddress:
    """The address components needed to establish a WebRTC Direct session."""

    host_protocol: str
    host: str
    port: int
    certificate_hash: str
    peer_id: ID
    direct_protocol: str = "p2p-webrtc-direct"

    @classmethod
    def parse(cls, address: str) -> "WebRTCDirectAddress":
        parts = address.strip("/").split("/")
        if len(parts) != 9:
            raise ValueError("invalid WebRTC Direct multiaddress")
        host_protocol, host, udp, port, direct, certhash, hash_value, p2p, peer = parts
        if host_protocol not in {"ip4", "ip6", "dns4", "dns6"}:
            raise ValueError("WebRTC Direct address requires an IP or DNS host")
        if udp != "udp" or direct not in {"webrtc-direct", "p2p-webrtc-direct"}:
            raise ValueError("WebRTC Direct address requires UDP and webrtc-direct")
        if certhash != "certhash" or p2p != "p2p":
            raise ValueError("WebRTC Direct address is missing certificate or peer ID")
        try:
            port_number = int(port)
        except ValueError as error:
            raise ValueError("WebRTC Direct port must be an integer") from error
        if not 0 < port_number <= 65535:
            raise ValueError("WebRTC Direct port is outside the valid range")
        if len(hash_value) < 2 or hash_value[0] not in {"u", "z"}:
            raise ValueError("WebRTC Direct certificate hash must use multibase")
        try:
            peer_id = ID.from_base58(peer)
        except ValueError as error:
            raise ValueError("invalid WebRTC Direct peer ID") from error
        decoded_hash = _decode_certificate_hash(hash_value)
        if len(decoded_hash) != 34 or decoded_hash[:2] != b"\x12\x20":
            raise ValueError("certificate hash must be a SHA-256 multihash")
        return cls(host_protocol, host, port_number, hash_value, peer_id, direct)

    def __str__(self) -> str:
        return (
            f"/{self.host_protocol}/{self.host}/udp/{self.port}"
            f"/{self.direct_protocol}/certhash/{self.certificate_hash}"
            f"/p2p/{self.peer_id}"
        )

    def certificate_matches(self, certificate_der: bytes) -> bool:
        """Return whether DER certificate bytes match the advertised hash."""
        digest = b"\x12\x20" + hashlib.sha256(certificate_der).digest()
        if self.certificate_hash.startswith("z"):
            encoded = "z" + base58.b58encode(digest).decode("ascii")
        elif self.certificate_hash.startswith("u"):
            encoded = "u" + base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
            if encoded != self.certificate_hash:
                # Older py-libp2p releases emitted base58 data with a `u` prefix.
                encoded = "u" + base58.b58encode(digest).decode("ascii")
        else:
            return False
        return encoded == self.certificate_hash


def _decode_certificate_hash(value: str) -> bytes:
    encoded = value[1:]
    try:
        if value.startswith("z"):
            return base58.b58decode(encoded)
        decoded = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
        if len(decoded) == 34 and decoded[:2] == b"\x12\x20":
            return decoded
        # Accept the historical `u` + base58 representation for compatibility.
        return base58.b58decode(encoded)
    except (ValueError, base64.binascii.Error) as error:
        raise ValueError("invalid WebRTC Direct certificate hash") from error
