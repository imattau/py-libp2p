"""Length-delimited framing for Circuit Relay v2 protobuf messages."""

from libp2p.io.utils import read_exactly
from libp2p.utils.varint import (
    decode_uvarint_from_stream,
    encode_varint_prefixed,
)

MAX_MESSAGE_SIZE = 4096


def encode_message(message: bytes) -> bytes:
    """Encode one protobuf message using a uvarint length prefix."""
    if len(message) > MAX_MESSAGE_SIZE:
        raise ValueError("Message exceeds maximum size")
    return encode_varint_prefixed(message)


async def read_message(stream) -> bytes:
    """Read one bounded, length-delimited protobuf message."""
    length = await decode_uvarint_from_stream(stream)
    if length > MAX_MESSAGE_SIZE:
        raise ValueError("Message exceeds maximum size")
    return await read_exactly(stream, length)
