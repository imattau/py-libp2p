"""Tests for Circuit Relay v2 control-message framing."""

from unittest.mock import AsyncMock

import pytest

from libp2p.relay.circuit_v2.framing import (
    MAX_MESSAGE_SIZE,
    encode_message,
    read_message,
)


def test_encode_message_uses_uvarint_length_prefix() -> None:
    assert encode_message(b"abc") == b"\x03abc"


def test_encode_message_rejects_oversized_payload() -> None:
    with pytest.raises(ValueError, match="maximum size"):
        encode_message(b"x" * (MAX_MESSAGE_SIZE + 1))


@pytest.mark.trio
async def test_read_message_handles_fragmented_frame() -> None:
    stream = AsyncMock()
    stream.read.side_effect = [b"\x03", b"abc"]

    assert await read_message(stream) == b"abc"
    assert stream.read.await_args_list[0].args == (1,)
    assert stream.read.await_args_list[1].args == (3,)


@pytest.mark.trio
async def test_read_message_rejects_oversized_payload() -> None:
    stream = AsyncMock()
    stream.read.side_effect = [b"\x81", b"\x20"]

    with pytest.raises(ValueError, match="maximum size"):
        await read_message(stream)
