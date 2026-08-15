import pytest

from libp2p.transport.webrtc.signaling import (
    WEBRTC_DIRECT_CREDENTIAL_PREFIX,
    WEBRTC_NOISE_PROLOGUE_PREFIX,
    WebRTCSignalingMessage,
    WebRTCSignalingType,
    encode_ice_candidate,
    munge_direct_sdp,
    new_direct_credentials,
    noise_prologue,
)


def test_direct_credentials_use_one_prefixed_random_value() -> None:
    first = new_direct_credentials()
    second = new_direct_credentials()

    assert first.username == first.password
    assert first.username.startswith(WEBRTC_DIRECT_CREDENTIAL_PREFIX)
    assert first.username != second.username


def test_munge_direct_sdp_replaces_attributes_and_preserves_crlf() -> None:
    credentials = new_direct_credentials()
    sdp = (
        "v=0\r\n"
        "a=ice-ufrag:old\r\n"
        "a=ice-pwd:old-password\r\n"
        "a=max-message-size:1200\r\n"
    )

    result = munge_direct_sdp(sdp, credentials)

    assert f"a=ice-ufrag:{credentials.username}\r\n" in result
    assert f"a=ice-pwd:{credentials.password}\r\n" in result
    assert result.count("a=max-message-size:16384") == 1
    assert "old-password" not in result
    assert result.endswith("\r\n")


def test_munge_direct_sdp_requires_ice_attributes() -> None:
    with pytest.raises(ValueError, match="ice-pwd"):
        munge_direct_sdp("v=0\na=ice-ufrag:present\n", new_direct_credentials())


def test_noise_prologue_has_specified_order() -> None:
    local = b"local-fingerprint"
    remote = b"remote-fingerprint"

    assert noise_prologue(local, remote) == (
        WEBRTC_NOISE_PROLOGUE_PREFIX + local + remote
    )


@pytest.mark.parametrize(
    "message",
    [
        WebRTCSignalingMessage(WebRTCSignalingType.SDP_OFFER, "v=0\\r\\n"),
        WebRTCSignalingMessage(WebRTCSignalingType.SDP_ANSWER, "v=0\\n"),
        WebRTCSignalingMessage(
            WebRTCSignalingType.ICE_CANDIDATE,
            '{"candidate":"candidate:1"}',
        ),
    ],
)
def test_signaling_message_round_trip(message: WebRTCSignalingMessage) -> None:
    assert WebRTCSignalingMessage.decode(message.encode()) == message


def test_signaling_message_matches_proto_wire_format() -> None:
    message = WebRTCSignalingMessage(WebRTCSignalingType.SDP_OFFER, "offer")

    assert message.encode() == b"\x09\x08\x00\x12\x05offer"


def test_signaling_message_rejects_trailing_or_missing_fields() -> None:
    with pytest.raises(ValueError, match="length"):
        WebRTCSignalingMessage.decode(b"\\x03\\x08\\x00")
    with pytest.raises(ValueError, match="missing fields"):
        WebRTCSignalingMessage.decode(b"\x00")


def test_ice_candidate_is_compact_deterministic_json() -> None:
    message = encode_ice_candidate({"sdpMid": "0", "candidate": "abc"})

    assert message.type is WebRTCSignalingType.ICE_CANDIDATE
    assert message.data == '{"candidate":"abc","sdpMid":"0"}'
