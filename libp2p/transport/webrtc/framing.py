"""Message framing shared by libp2p WebRTC and WebRTC Direct."""

from dataclasses import dataclass

from google.protobuf.message import DecodeError

from libp2p.utils.varint import encode_uvarint

from .pb import webrtc_pb2

MAX_MESSAGE_SIZE = 16 * 1024


@dataclass(frozen=True)
class WebRTCFrame:
    """One libp2p WebRTC data-channel frame."""

    message: bytes = b""
    flag: int | None = None


def encode_frame(frame: WebRTCFrame) -> bytes:
    """Encode one protobuf frame with its unsigned-varint length prefix."""
    if len(frame.message) > MAX_MESSAGE_SIZE:
        raise ValueError("WebRTC frame exceeds the 16 KiB message limit")
    if frame.flag is None and not frame.message:
        raise ValueError("WebRTC frame must contain data or a flag")

    message = webrtc_pb2.Message(message=frame.message)
    if frame.flag is not None:
        try:
            message.flag = frame.flag
        except ValueError as error:
            raise ValueError(f"unknown WebRTC frame flag: {frame.flag}") from error
    encoded = message.SerializeToString()
    framed_size = len(encoded) + len(encode_uvarint(len(encoded)))
    if framed_size > MAX_MESSAGE_SIZE:
        raise ValueError("encoded WebRTC frame exceeds the 16 KiB message limit")
    return encode_uvarint(len(encoded)) + encoded


def decode_frames(buffer: bytes) -> tuple[list[WebRTCFrame], bytes]:
    """Decode complete frames, retaining an incomplete suffix for the caller."""
    frames: list[WebRTCFrame] = []
    offset = 0
    while offset < len(buffer):
        length = _decode_length(buffer[offset:])
        if length is None:
            break
        frame_size, prefix_size = length
        if frame_size > MAX_MESSAGE_SIZE:
            raise ValueError("encoded WebRTC frame exceeds the 16 KiB message limit")
        start = offset + prefix_size
        end = start + frame_size
        if end > len(buffer):
            break
        message = webrtc_pb2.Message()
        try:
            message.ParseFromString(buffer[start:end])
        except DecodeError as error:
            raise ValueError("invalid WebRTC frame protobuf") from error
        frames.append(
            WebRTCFrame(
                message=message.message,
                flag=message.flag if message.HasField("flag") else None,
            )
        )
        offset = end
    return frames, buffer[offset:]


def _decode_length(data: bytes) -> tuple[int, int] | None:
    value = 0
    for index, byte in enumerate(data):
        value |= (byte & 0x7F) << (index * 7)
        if byte < 0x80:
            return value, index + 1
        if index >= 9:
            raise ValueError("WebRTC frame length varint is too long")
    return None
