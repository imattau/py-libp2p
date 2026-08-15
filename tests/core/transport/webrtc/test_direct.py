import hashlib

import pytest
import base58

from libp2p.crypto.ed25519 import create_new_key_pair
from libp2p.peer.id import ID
from libp2p.transport.webrtc.direct import WebRTCDirectAddress


def _address(certificate: bytes) -> tuple[str, object]:
    peer_id = create_new_key_pair(b"2" * 32).public_key
    digest = b"\x12\x20" + hashlib.sha256(certificate).digest()
    certhash = "u" + base58.b58encode(digest).decode()
    peer = str(ID.from_pubkey(peer_id))
    return (
        f"/ip4/127.0.0.1/udp/4001/p2p-webrtc-direct/certhash/{certhash}/p2p/{peer}",
        peer_id,
    )


def test_parse_and_validate_certificate_hash() -> None:
    certificate = b"test-certificate"
    address, _ = _address(certificate)
    parsed = WebRTCDirectAddress.parse(address)

    assert str(parsed) == address
    assert parsed.certificate_matches(certificate)
    assert not parsed.certificate_matches(b"different")


def test_rejects_malformed_direct_address() -> None:
    with pytest.raises(ValueError, match="certificate hash"):
        WebRTCDirectAddress.parse(
            "/ip4/127.0.0.1/udp/4001/p2p-webrtc-direct/certhash/nope/p2p/QmPeer"
        )
