from dataclasses import dataclass
from typing import Any

from aioquic.quic.events import (
    ConnectionTerminated,
    HandshakeCompleted,
    StreamDataReceived,
)


@dataclass(frozen=True)
class QuicHandshakeComplete:
    alpn_protocol: str | None
    early_data_accepted: bool
    session_resumed: bool


@dataclass(frozen=True)
class QuicStreamData:
    stream_id: int
    data: bytes
    end_stream: bool


@dataclass(frozen=True)
class QuicConnectionClosed:
    error_code: int
    frame_type: int | None
    reason_phrase: str


def normalize_event(event: Any) -> Any:
    """Convert aioquic events into transport-owned event types."""
    if isinstance(event, HandshakeCompleted):
        return QuicHandshakeComplete(
            alpn_protocol=event.alpn_protocol,
            early_data_accepted=event.early_data_accepted,
            session_resumed=event.session_resumed,
        )
    if isinstance(event, StreamDataReceived):
        return QuicStreamData(
            stream_id=event.stream_id,
            data=event.data,
            end_stream=event.end_stream,
        )
    if isinstance(event, ConnectionTerminated):
        return QuicConnectionClosed(
            error_code=event.error_code,
            frame_type=event.frame_type,
            reason_phrase=event.reason_phrase,
        )
    return event
