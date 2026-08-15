"""WebRTC Direct multiaddress and certificate-hash handling."""

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

    @classmethod
    def parse(cls, address: str) -> "WebRTCDirectAddress":
        parts = address.strip("/").split("/")
        if len(parts) != 9:
            raise ValueError("invalid WebRTC Direct multiaddress")
        host_protocol, host, udp, port, direct, certhash, hash_value, p2p, peer = parts
        if host_protocol not in {"ip4", "ip6", "dns4", "dns6"}:
            raise ValueError("WebRTC Direct address requires an IP or DNS host")
        if udp != "udp" or direct != "p2p-webrtc-direct":
            raise ValueError("WebRTC Direct address requires UDP and p2p-webrtc-direct")
        if certhash != "certhash" or p2p != "p2p":
            raise ValueError("WebRTC Direct address is missing certificate or peer ID")
        try:
            port_number = int(port)
        except ValueError as error:
            raise ValueError("WebRTC Direct port must be an integer") from error
        if not 0 < port_number <= 65535:
            raise ValueError("WebRTC Direct port is outside the valid range")
        if not hash_value.startswith("u") or len(hash_value) < 2:
            raise ValueError("WebRTC Direct certificate hash must use base58btc")
        try:
            peer_id = ID.from_base58(peer)
        except ValueError as error:
            raise ValueError("invalid WebRTC Direct peer ID") from error
        try:
            decoded_hash = base58.b58decode(hash_value[1:])
        except ValueError as error:
            raise ValueError("invalid WebRTC Direct certificate hash") from error
        if len(decoded_hash) != 34 or decoded_hash[:2] != b"\x12\x20":
            raise ValueError("certificate hash must be a SHA-256 multihash")
        return cls(host_protocol, host, port_number, hash_value, peer_id)

    def __str__(self) -> str:
        return (
            f"/{self.host_protocol}/{self.host}/udp/{self.port}"
            f"/p2p-webrtc-direct/certhash/{self.certificate_hash}"
            f"/p2p/{self.peer_id}"
        )

    def certificate_matches(self, certificate_der: bytes) -> bool:
        """Return whether DER certificate bytes match the advertised hash."""
        digest = b"\x12\x20" + hashlib.sha256(certificate_der).digest()
        encoded = "u" + base58.b58encode(digest).decode("ascii")
        return encoded == self.certificate_hash
