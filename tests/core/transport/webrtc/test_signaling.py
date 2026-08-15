import pytest

from libp2p.transport.webrtc.signaling import (
    WEBRTC_DIRECT_CREDENTIAL_PREFIX,
    WEBRTC_NOISE_PROLOGUE_PREFIX,
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
