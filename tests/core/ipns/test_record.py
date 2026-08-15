from datetime import datetime, timezone

import pytest

from libp2p.crypto.ed25519 import create_new_key_pair
from libp2p.ipns.pb import ipns_pb2
from libp2p.ipns.record import (
    IPNS_SIGNATURE_PREFIX,
    IpnsRecordStore,
    validate_ipns_record,
)

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _uint(value: int) -> bytes:
    if value < 24:
        return bytes([value])
    if value < 256:
        return b"\x18" + bytes([value])
    if value < 2**32:
        return b"\x1a" + value.to_bytes(4, "big")
    return b"\x1b" + value.to_bytes(8, "big")


def _bytes(value: bytes) -> bytes:
    if len(value) >= 24:
        raise ValueError("test fixture only supports short byte strings")
    return bytes([0x40 + len(value)]) + value


def _text(value: str) -> bytes:
    encoded = value.encode()
    return bytes([0x60 + len(encoded)]) + encoded


def _data(value: bytes = b"/ipfs/bafytest", sequence: int = 1) -> bytes:
    fields = [
        (_text("TTL"), _uint(300_000_000_000)),
        (_text("Value"), _bytes(value)),
        (_text("Sequence"), _uint(sequence)),
        (_text("Validity"), _bytes(b"2026-01-02T00:00:00Z")),
        (_text("ValidityType"), _uint(0)),
    ]
    return bytes([0xA0 + len(fields)]) + b"".join(key + value for key, value in fields)


def _record(sequence: int = 1, *, legacy_sequence: int | None = None) -> bytes:
    key_pair = create_new_key_pair(b"1" * 32)
    data = _data(sequence=sequence)
    entry = ipns_pb2.IpnsEntry(
        data=data,
        signatureV2=key_pair.private_key.sign(IPNS_SIGNATURE_PREFIX + data),
        pubKey=key_pair.public_key.serialize(),
    )
    entry.value = b"/ipfs/bafytest"
    entry.validity = b"2026-01-02T00:00:00Z"
    entry.validityType = 0
    entry.sequence = sequence if legacy_sequence is None else legacy_sequence
    entry.ttl = 300_000_000_000
    return entry.SerializeToString()


def test_validate_ipns_record_checks_signature_and_fields() -> None:
    record = validate_ipns_record(_record(), now=NOW)

    assert record.value == b"/ipfs/bafytest"
    assert record.sequence == 1
    assert record.ttl == 300_000_000_000


def test_validate_ipns_record_rejects_expired_record() -> None:
    with pytest.raises(ValueError, match="expired"):
        validate_ipns_record(_record(), now=datetime(2026, 1, 3, tzinfo=timezone.utc))


def test_validate_ipns_record_rejects_legacy_mismatch() -> None:
    with pytest.raises(ValueError, match="sequence"):
        validate_ipns_record(_record(legacy_sequence=2), now=NOW)


def test_record_store_keeps_highest_sequence() -> None:
    store = IpnsRecordStore()
    assert store.put(b"name", _record(2), now=NOW)
    assert not store.put(b"name", _record(1), now=NOW)
    assert store.get(b"name").sequence == 2  # type: ignore[union-attr]
