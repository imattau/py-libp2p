import pytest

from libp2p.transport.webrtc.framing import (
    MAX_MESSAGE_SIZE,
    WebRTCFrame,
    decode_frames,
    encode_frame,
)
from libp2p.transport.webrtc.pb import webrtc_pb2


def test_data_frame_round_trips_and_supports_partial_input() -> None:
    encoded = encode_frame(WebRTCFrame(b"hello"))

    frames, remainder = decode_frames(encoded[:2])
    assert frames == []
    assert remainder == encoded[:2]

    frames, remainder = decode_frames(remainder + encoded[2:])
    assert frames == [WebRTCFrame(b"hello")]
    assert remainder == b""

    frames, remainder = decode_frames(b"\x81")
    assert frames == []
    assert remainder == b"\x81"


def test_control_flags_round_trip() -> None:
    encoded = b"".join(
        encode_frame(WebRTCFrame(flag=flag))
        for flag in (
            webrtc_pb2.Message.FIN,
            webrtc_pb2.Message.STOP_SENDING,
            webrtc_pb2.Message.RESET_STREAM,
            webrtc_pb2.Message.FIN_ACK,
        )
    )

    frames, remainder = decode_frames(encoded)
    assert [frame.flag for frame in frames] == [0, 1, 2, 3]
    assert remainder == b""


def test_message_limit_is_enforced() -> None:
    with pytest.raises(ValueError, match="16 KiB"):
        encode_frame(WebRTCFrame(b"x" * (MAX_MESSAGE_SIZE + 1)))

    encoded = b"\x81\x80\x01" + b"\x00" * 128
    with pytest.raises(ValueError, match="16 KiB"):
        decode_frames(encoded)
