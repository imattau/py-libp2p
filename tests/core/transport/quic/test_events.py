from aioquic.quic.events import (
    ConnectionTerminated,
    HandshakeCompleted,
    StreamDataReceived,
)

from libp2p.transport.quic.events import (
    QuicConnectionClosed,
    QuicHandshakeComplete,
    QuicStreamData,
    normalize_event,
)


def test_normalize_handshake_event():
    assert normalize_event(HandshakeCompleted("libp2p", True, False)) == (
        QuicHandshakeComplete("libp2p", True, False)
    )


def test_normalize_stream_data_event():
    assert normalize_event(StreamDataReceived(b"payload", True, 7)) == (
        QuicStreamData(7, b"payload", True)
    )


def test_normalize_connection_termination_event():
    assert normalize_event(ConnectionTerminated(42, 6, "closed")) == (
        QuicConnectionClosed(42, 6, "closed")
    )


def test_normalize_preserves_unknown_events():
    event = object()

    assert normalize_event(event) is event
