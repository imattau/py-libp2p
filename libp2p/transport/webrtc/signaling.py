"""Protocol helpers shared by the WebRTC Direct signaling flows."""

from dataclasses import dataclass
from enum import IntEnum
import json
import secrets
from typing import TYPE_CHECKING

from libp2p.abc import INetStream
from libp2p.utils.varint import (
    decode_varint_with_size,
    encode_uvarint,
    encode_varint_prefixed,
    read_varint_prefixed_bytes,
)

if TYPE_CHECKING:
    from .aiortc_engine import SessionDescription

WEBRTC_DIRECT_CREDENTIAL_PREFIX = "libp2p+webrtc+v1/"
WEBRTC_NOISE_PROLOGUE_PREFIX = b"libp2p-webrtc-noise:"
WEBRTC_MAX_MESSAGE_SIZE = 16 * 1024
WEBRTC_SIGNALING_PROTOCOL = "/webrtc-signaling/0.0.1"


class WebRTCSignalingType(IntEnum):
    SDP_OFFER = 0
    SDP_ANSWER = 1
    ICE_CANDIDATE = 2


def session_description_message(
    description: "SessionDescription",
) -> "WebRTCSignalingMessage":
    """Convert an aiortc session description to a signaling message."""
    try:
        message_type = {
            "offer": WebRTCSignalingType.SDP_OFFER,
            "answer": WebRTCSignalingType.SDP_ANSWER,
        }[description.type]
    except KeyError as error:
        raise ValueError(
            f"unsupported WebRTC session description: {description.type}"
        ) from error
    return WebRTCSignalingMessage(message_type, description.sdp)


def session_description_from_message(
    message: "WebRTCSignalingMessage",
) -> "SessionDescription":
    """Convert an SDP signaling message to an aiortc session description."""
    if message.type not in {
        WebRTCSignalingType.SDP_OFFER,
        WebRTCSignalingType.SDP_ANSWER,
    }:
        raise ValueError("WebRTC signaling message does not contain SDP")
    from .aiortc_engine import SessionDescription

    description_type = (
        "offer" if message.type is WebRTCSignalingType.SDP_OFFER else "answer"
    )
    return SessionDescription(description_type, message.data)


@dataclass(frozen=True)
class WebRTCSignalingMessage:
    """One message from the browser-to-browser signaling protocol."""

    type: WebRTCSignalingType
    data: str

    def encode(self) -> bytes:
        """Encode the proto3 message, including its uvarint length prefix."""
        encoded_type = b"\x08" + encode_uvarint(int(self.type))
        encoded_data = self.data.encode("utf-8")
        payload = (
            encoded_type
            + b"\x12"
            + encode_uvarint(len(encoded_data))
            + encoded_data
        )
        return encode_varint_prefixed(payload)

    @classmethod
    def decode(cls, encoded: bytes) -> "WebRTCSignalingMessage":
        """Decode one length-prefixed signaling message."""
        length, prefix_size = decode_varint_with_size(encoded)
        if prefix_size == 0 or len(encoded) != prefix_size + length:
            raise ValueError("invalid WebRTC signaling message length")
        payload = encoded[prefix_size:]
        message_type: int | None = None
        data: str | None = None
        offset = 0
        while offset < len(payload):
            tag, tag_size = decode_varint_with_size(payload[offset:])
            if tag_size == 0:
                raise ValueError("invalid WebRTC signaling field tag")
            offset += tag_size
            field_number, wire_type = tag >> 3, tag & 7
            if field_number == 1 and wire_type == 0:
                message_type, value_size = decode_varint_with_size(payload[offset:])
                if value_size == 0:
                    raise ValueError("invalid WebRTC signaling type")
                offset += value_size
            elif field_number == 2 and wire_type == 2:
                data_length, value_size = decode_varint_with_size(payload[offset:])
                if value_size == 0:
                    raise ValueError("invalid WebRTC signaling data length")
                offset += value_size
                end = offset + data_length
                if end > len(payload):
                    raise ValueError("truncated WebRTC signaling data")
                try:
                    data = payload[offset:end].decode("utf-8")
                except UnicodeDecodeError as error:
                    raise ValueError("WebRTC signaling data is not UTF-8") from error
                offset = end
            else:
                raise ValueError("unsupported WebRTC signaling field")
        if message_type is None or data is None:
            raise ValueError("WebRTC signaling message is missing fields")
        try:
            parsed_type = WebRTCSignalingType(message_type)
        except ValueError as error:
            raise ValueError(
                f"unknown WebRTC signaling type: {message_type}"
            ) from error
        return cls(parsed_type, data)


def encode_ice_candidate(candidate: object) -> WebRTCSignalingMessage:
    """Encode an aiortc/browser ICE candidate JSON object for signaling."""
    return WebRTCSignalingMessage(
        WebRTCSignalingType.ICE_CANDIDATE,
        json.dumps(candidate, separators=(",", ":"), sort_keys=True),
    )


async def read_signaling_message(stream: INetStream) -> WebRTCSignalingMessage:
    """Read one length-prefixed message from a libp2p stream."""
    payload = await read_varint_prefixed_bytes(stream)
    return WebRTCSignalingMessage.decode(encode_varint_prefixed(payload))


async def write_signaling_message(
    stream: INetStream, message: WebRTCSignalingMessage
) -> None:
    """Write one length-prefixed message to a libp2p stream."""
    await stream.write(message.encode())


@dataclass(frozen=True)
class WebRTCDirectCredentials:
    """ICE credentials used by a WebRTC Direct browser offer."""

    username: str
    password: str


def new_direct_credentials() -> WebRTCDirectCredentials:
    """Create the single random credential value required by WebRTC Direct."""
    value = WEBRTC_DIRECT_CREDENTIAL_PREFIX + secrets.token_urlsafe(24)
    return WebRTCDirectCredentials(username=value, password=value)


def munge_direct_sdp(
    sdp: str,
    credentials: WebRTCDirectCredentials,
    max_message_size: int = WEBRTC_MAX_MESSAGE_SIZE,
) -> str:
    """
    Apply the WebRTC Direct ICE credentials and message-size attribute.

    aiortc generates the SDP structure and certificates. Direct signaling
    supplies the ICE credentials and requires the SCTP message-size limit.
    Existing attributes are replaced so this is safe to apply more than once.
    """
    if max_message_size <= 0:
        raise ValueError("max_message_size must be positive")

    newline = "\r\n" if "\r\n" in sdp else "\n"
    trailing_newline = sdp.endswith(("\r\n", "\n"))
    lines = sdp.replace("\r\n", "\n").split("\n")
    if trailing_newline:
        lines.pop()

    replaced = {"a=ice-ufrag": False, "a=ice-pwd": False}
    result: list[str] = []
    for line in lines:
        if line.startswith("a=ice-ufrag:"):
            result.append(f"a=ice-ufrag:{credentials.username}")
            replaced["a=ice-ufrag"] = True
        elif line.startswith("a=ice-pwd:"):
            result.append(f"a=ice-pwd:{credentials.password}")
            replaced["a=ice-pwd"] = True
        elif line.startswith("a=max-message-size:"):
            result.append(f"a=max-message-size:{max_message_size}")
        else:
            result.append(line)

    missing = [name for name, present in replaced.items() if not present]
    if missing:
        raise ValueError(f"SDP is missing required attribute(s): {', '.join(missing)}")

    if not any(line.startswith("a=max-message-size:") for line in result):
        result.append(f"a=max-message-size:{max_message_size}")

    rendered = newline.join(result)
    return rendered + (newline if trailing_newline else "")


def noise_prologue(
    local_certificate_fingerprint: bytes,
    remote_certificate_fingerprint: bytes,
) -> bytes:
    """Build the Noise XX prologue used after the WebRTC DTLS handshake."""
    return (
        WEBRTC_NOISE_PROLOGUE_PREFIX
        + local_certificate_fingerprint
        + remote_certificate_fingerprint
    )
