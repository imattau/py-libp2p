"""Protocol helpers shared by the WebRTC Direct signaling flows."""

from dataclasses import dataclass
import secrets

WEBRTC_DIRECT_CREDENTIAL_PREFIX = "libp2p+webrtc+v1/"
WEBRTC_NOISE_PROLOGUE_PREFIX = b"libp2p-webrtc-noise:"
WEBRTC_MAX_MESSAGE_SIZE = 16 * 1024


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
