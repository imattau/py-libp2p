"""IPNS record validation and monotonic record storage."""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from google.protobuf.message import DecodeError

from libp2p.crypto.keys import PublicKey
from libp2p.peer.envelope import pub_key_from_protobuf
import libp2p.peer.pb.crypto_pb2 as crypto_pb

from .pb import ipns_pb2

IPNS_SIGNATURE_PREFIX = b"ipns-signature:"
MAX_IPNS_RECORD_SIZE = 10 * 1024


@dataclass(frozen=True)
class IpnsRecord:
    """A validated IPNS record and its decoded signed data."""

    entry: ipns_pb2.IpnsEntry
    data: dict[str, Any]
    public_key: PublicKey

    @property
    def value(self) -> bytes:
        return self.data["Value"]

    @property
    def sequence(self) -> int:
        return self.data["Sequence"]

    @property
    def ttl(self) -> int:
        return self.data["TTL"]


def validate_ipns_record(
    raw_record: bytes,
    *,
    public_key: PublicKey | None = None,
    now: datetime | None = None,
    max_size: int = MAX_IPNS_RECORD_SIZE,
) -> IpnsRecord:
    """Parse and validate an IPNS record according to the V2 rules."""
    if len(raw_record) > max_size:
        raise ValueError("IPNS record exceeds the size limit")

    entry = ipns_pb2.IpnsEntry()
    try:
        entry.ParseFromString(raw_record)
    except DecodeError as error:
        raise ValueError("invalid IPNS protobuf") from error
    if not entry.data or not entry.signatureV2:
        raise ValueError("IPNS record requires data and signatureV2")

    record_key = public_key
    if entry.pubKey:
        try:
            record_key = pub_key_from_protobuf(
                crypto_pb.PublicKey.FromString(entry.pubKey)
            )
        except Exception as error:
            raise ValueError("invalid IPNS public key") from error
    if record_key is None:
        raise ValueError("IPNS public key is required for validation")

    data = _decode_data(entry.data)
    _validate_required_fields(data)
    if not record_key.verify(IPNS_SIGNATURE_PREFIX + entry.data, entry.signatureV2):
        raise ValueError("invalid IPNS signature")
    _validate_legacy_fields(entry, data)

    expiration = _parse_expiration(data["Validity"])
    current_time = now or datetime.now(timezone.utc)
    if expiration <= current_time:
        raise ValueError("IPNS record has expired")

    return IpnsRecord(entry, data, record_key)


class IpnsRecordStore:
    """Store only valid IPNS records, retaining the highest sequence number."""

    def __init__(self) -> None:
        self._records: dict[bytes, IpnsRecord] = {}

    def put(
        self,
        name: bytes,
        raw_record: bytes,
        *,
        public_key: PublicKey | None = None,
        now: datetime | None = None,
    ) -> bool:
        record = validate_ipns_record(raw_record, public_key=public_key, now=now)
        existing = self._records.get(name)
        if existing is not None and existing.sequence >= record.sequence:
            return False
        self._records[name] = record
        return True

    def get(self, name: bytes) -> IpnsRecord | None:
        return self._records.get(name)

    def remove(self, name: bytes) -> None:
        self._records.pop(name, None)


def _decode_data(raw_data: bytes) -> dict[str, Any]:
    decoder = _CborDecoder(raw_data)
    value = decoder.decode()
    if decoder.offset != len(raw_data) or not isinstance(value, dict):
        raise ValueError("IPNS data must be one DAG-CBOR map")
    if not all(isinstance(key, str) for key in value):
        raise ValueError("IPNS data keys must be strings")
    return value


def _validate_required_fields(data: dict[str, Any]) -> None:
    required = {"Value", "Validity", "ValidityType", "Sequence", "TTL"}
    if not required.issubset(data):
        raise ValueError("IPNS data is missing required fields")
    if not isinstance(data["Value"], bytes) or not isinstance(data["Validity"], bytes):
        raise ValueError("IPNS Value and Validity must be byte strings")
    if data["ValidityType"] != 0 or not isinstance(data["Sequence"], int):
        raise ValueError("IPNS data contains an unsupported validity or sequence")
    if not isinstance(data["TTL"], int) or data["Sequence"] < 0 or data["TTL"] < 0:
        raise ValueError("IPNS Sequence and TTL must be unsigned integers")


def _validate_legacy_fields(entry: ipns_pb2.IpnsEntry, data: dict[str, Any]) -> None:
    if entry.HasField("value") and entry.value != data["Value"]:
        raise ValueError("legacy IPNS value does not match signed data")
    if entry.HasField("validity") and entry.validity != data["Validity"]:
        raise ValueError("legacy IPNS validity does not match signed data")
    if entry.HasField("validityType") and entry.validityType != data["ValidityType"]:
        raise ValueError("legacy IPNS validity type does not match signed data")
    if entry.HasField("sequence") and entry.sequence != data["Sequence"]:
        raise ValueError("legacy IPNS sequence does not match signed data")
    if entry.HasField("ttl") and entry.ttl != data["TTL"]:
        raise ValueError("legacy IPNS TTL does not match signed data")


def _parse_expiration(value: bytes) -> datetime:
    try:
        expiration = datetime.fromisoformat(
            value.decode("ascii").replace("Z", "+00:00")
        )
    except (UnicodeDecodeError, ValueError) as error:
        raise ValueError("IPNS validity is not RFC3339") from error
    if expiration.tzinfo is None:
        raise ValueError("IPNS validity must include a timezone")
    return expiration.astimezone(timezone.utc)


class _CborDecoder:
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.offset = 0

    def decode(self) -> Any:
        if self.offset >= len(self.data):
            raise ValueError("truncated DAG-CBOR data")
        initial = self._read_byte()
        major = initial >> 5
        additional = initial & 0x1F
        if additional == 31:
            raise ValueError("indefinite-length DAG-CBOR is not supported")
        length = self._read_length(additional)
        if major == 0:
            return length
        if major == 2:
            return self._read(length)
        if major == 3:
            try:
                return self._read(length).decode("utf-8")
            except UnicodeDecodeError as error:
                raise ValueError("invalid DAG-CBOR string") from error
        if major == 4:
            return [self.decode() for _ in range(length)]
        if major == 5:
            result: dict[Any, Any] = {}
            for _ in range(length):
                key = self.decode()
                if key in result:
                    raise ValueError("duplicate DAG-CBOR map key")
                result[key] = self.decode()
            return result
        raise ValueError("unsupported DAG-CBOR value")

    def _read_byte(self) -> int:
        value = self.data[self.offset]
        self.offset += 1
        return value

    def _read_length(self, additional: int) -> int:
        if additional < 24:
            return additional
        size = {24: 1, 25: 2, 26: 4, 27: 8}.get(additional)
        if size is None:
            raise ValueError("unsupported DAG-CBOR length")
        return int.from_bytes(self._read(size), "big")

    def _read(self, size: int) -> bytes:
        end = self.offset + size
        if end > len(self.data):
            raise ValueError("truncated DAG-CBOR data")
        value = self.data[self.offset : end]
        self.offset = end
        return value
