"""Tests for Circuit Relay v2 reservation vouchers."""

import pytest

from libp2p.crypto.ed25519 import create_new_key_pair
from libp2p.peer.id import ID
from libp2p.relay.circuit_v2.voucher import (
    Voucher,
    create_voucher,
    verify_voucher,
)


def test_voucher_is_signed_and_contains_claims() -> None:
    key_pair = create_new_key_pair(seed=b"r" * 32)
    relay_id = ID.from_pubkey(key_pair.public_key)
    peer_id = ID.from_base58("QmNM23MiU1Kd7yfiKVdUnaDo8RYca8By4zDmr7uSaVV8Px")
    expiration = 1_800_000_000

    voucher = create_voucher(relay_id, peer_id, expiration, key_pair.private_key)

    verify_voucher(voucher, relay_id, peer_id, expiration)

    from libp2p.peer.envelope import unmarshal_envelope

    envelope = unmarshal_envelope(voucher)
    payload = Voucher.FromString(envelope.raw_payload)
    assert payload.relay == relay_id.to_bytes()
    assert payload.peer == peer_id.to_bytes()
    assert payload.expiration == expiration


def test_voucher_rejects_mismatched_claims() -> None:
    key_pair = create_new_key_pair(seed=b"s" * 32)
    relay_id = ID.from_pubkey(key_pair.public_key)
    peer_id = ID.from_base58("QmNM23MiU1Kd7yfiKVdUnaDo8RYca8By4zDmr7uSaVV8Px")
    voucher = create_voucher(relay_id, peer_id, 1_800_000_000, key_pair.private_key)

    with pytest.raises(ValueError, match="claims"):
        verify_voucher(voucher, relay_id, peer_id, 1_800_000_001)
