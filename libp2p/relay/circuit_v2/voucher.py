"""Signed reservation vouchers for Circuit Relay v2."""

from google.protobuf import descriptor_pb2, descriptor_pool
from google.protobuf.message_factory import GetMessageClass

from libp2p.crypto.keys import PrivateKey
from libp2p.peer.envelope import Envelope, make_unsigned
from libp2p.peer.id import ID

VOUCHER_DOMAIN = "libp2p-relay-rsvp"
VOUCHER_CODEC = b"\x03\x02"


def _voucher_class():
    file_descriptor = descriptor_pb2.FileDescriptorProto(
        name="libp2p/relay/circuit_v2/voucher.proto",
        package="circuit.pb.v2",
        syntax="proto3",
    )
    message = file_descriptor.message_type.add(name="Voucher")
    for name, field_type in (
        ("relay", descriptor_pb2.FieldDescriptorProto.TYPE_BYTES),
        ("peer", descriptor_pb2.FieldDescriptorProto.TYPE_BYTES),
        ("expiration", descriptor_pb2.FieldDescriptorProto.TYPE_UINT64),
    ):
        message.field.add(
            name=name,
            number=len(message.field) + 1,
            label=descriptor_pb2.FieldDescriptorProto.LABEL_OPTIONAL,
            type=field_type,
        )
    descriptor = descriptor_pool.Default().AddSerializedFile(
        file_descriptor.SerializeToString()
    )
    return GetMessageClass(descriptor.message_types_by_name["Voucher"])


Voucher = _voucher_class()


def create_voucher(
    relay_id: ID,
    peer_id: ID,
    expiration: int,
    private_key: PrivateKey,
) -> bytes:
    """Create a signed relay reservation voucher envelope."""
    payload = Voucher(
        relay=relay_id.to_bytes(),
        peer=peer_id.to_bytes(),
        expiration=expiration,
    ).SerializeToString(deterministic=True)
    signature = private_key.sign(
        make_unsigned(VOUCHER_DOMAIN, VOUCHER_CODEC, payload)
    )
    envelope = Envelope(
        public_key=private_key.get_public_key(),
        payload_type=VOUCHER_CODEC,
        raw_payload=payload,
        signature=signature,
    )
    return envelope.marshal_envelope()


def verify_voucher(data: bytes, relay_id: ID, peer_id: ID, expiration: int) -> None:
    """Verify a voucher's envelope and claims."""
    from libp2p.peer.envelope import unmarshal_envelope

    envelope = unmarshal_envelope(data)
    if envelope.payload_type != VOUCHER_CODEC:
        raise ValueError("Invalid reservation voucher payload type")
    envelope.validate(VOUCHER_DOMAIN)
    voucher = Voucher.FromString(envelope.raw_payload)
    if (
        voucher.relay != relay_id.to_bytes()
        or voucher.peer != peer_id.to_bytes()
        or voucher.expiration != expiration
    ):
        raise ValueError("Reservation voucher claims do not match")
