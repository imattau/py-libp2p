"""Optional aiortc integration for the Trio WebRTC transport boundary."""

from dataclasses import dataclass
from typing import Any

from .asyncio_bridge import AsyncioLoopThread
from .connection import WebRTCConnection


class WebRTCDependencyError(RuntimeError):
    """Raised when the optional aiortc WebRTC engine is unavailable."""


@dataclass(frozen=True)
class SessionDescription:
    type: str
    sdp: str


class AiortcWebRTCEngine:
    """Own one aiortc peer connection on the dedicated asyncio loop."""

    def __init__(self, ice_servers: tuple[str, ...] = ()) -> None:
        self.ice_servers = ice_servers
        self.bridge = AsyncioLoopThread()
        self._peer_connection: Any | None = None

    async def start(self) -> None:
        await self.bridge.start()
        try:
            self._peer_connection = await self.bridge.call(
                _new_peer_connection, self.ice_servers
            )
        except Exception:
            await self.bridge.close()
            raise

    async def create_offer(self) -> SessionDescription:
        peer_connection = self._require_peer_connection()
        description = await self.bridge.call(_create_offer, peer_connection)
        return SessionDescription(description.type, description.sdp)

    async def create_answer(self) -> SessionDescription:
        peer_connection = self._require_peer_connection()
        description = await self.bridge.call(_create_answer, peer_connection)
        return SessionDescription(description.type, description.sdp)

    async def set_remote_description(self, description: SessionDescription) -> None:
        peer_connection = self._require_peer_connection()
        await self.bridge.call(
            _set_remote_description,
            peer_connection,
            description.type,
            description.sdp,
        )

    async def create_data_channel(
        self,
        connection_role: bool,
        *,
        negotiated: bool = False,
        channel_id: int | None = None,
        label: str = "",
    ) -> WebRTCConnection:
        """
        Create a libp2p data channel and adapt it to Trio.

        WebRTC Direct uses ``negotiated=True``, id 0, and an empty label.
        Browser-to-browser signaling first creates a non-negotiated ``init``
        channel so the offer contains the SCTP media section.
        """
        peer_connection = self._require_peer_connection()
        channel = await self.bridge.call(
            _create_data_channel,
            peer_connection,
            label,
            negotiated,
            channel_id,
        )
        connection = WebRTCConnection(
            channel,
            self.bridge.call,
            is_initiator=connection_role,
        )
        await self.bridge.call(
            _register_message_handler, channel, connection.on_message
        )
        return connection

    async def create_init_data_channel(self) -> None:
        """Create the browser-to-browser signaling ``init`` channel."""
        peer_connection = self._require_peer_connection()
        await self.bridge.call(
            _create_data_channel, peer_connection, "init", False, None
        )

    async def create_direct_data_channel(
        self, connection_role: bool
    ) -> WebRTCConnection:
        """Create the negotiated WebRTC Direct channel at SCTP stream 0."""
        return await self.create_data_channel(
            connection_role,
            negotiated=True,
            channel_id=0,
            label="",
        )

    async def add_ice_candidate(self, candidate: Any) -> None:
        """Pass a browser/aiortc ICE candidate to the peer connection."""
        peer_connection = self._require_peer_connection()
        await self.bridge.call(_add_ice_candidate, peer_connection, candidate)

    async def add_ice_candidate_data(self, candidate: dict[str, Any]) -> None:
        """Parse a signaling candidate and pass it to aiortc."""
        peer_connection = self._require_peer_connection()
        await self.bridge.call(
            _add_ice_candidate_data, peer_connection, candidate
        )

    async def on_data_channel(self, handler: Any) -> None:
        """Register a Trio-facing callback for remotely-created channels."""
        peer_connection = self._require_peer_connection()
        await self.bridge.call(_register_data_channel_handler, peer_connection, handler)

    async def on_ice_candidate(self, handler: Any) -> None:
        """Register a callback for local trickle ICE candidates."""
        peer_connection = self._require_peer_connection()
        await self.bridge.call(
            _register_ice_candidate_handler, peer_connection, handler
        )

    async def close(self) -> None:
        if self._peer_connection is not None:
            await self.bridge.call(self._peer_connection.close)
            self._peer_connection = None
        await self.bridge.close()

    def _require_peer_connection(self) -> Any:
        if self._peer_connection is None:
            raise RuntimeError("WebRTC engine has not been started")
        return self._peer_connection


def _load_aiortc() -> tuple[Any, Any, Any]:
    try:
        from aiortc import (
            RTCConfiguration,
            RTCIceCandidate,
            RTCIceServer,
            RTCPeerConnection,
            RTCSessionDescription,
        )
    except ImportError as error:
        raise WebRTCDependencyError(
            "WebRTC support requires the optional 'aiortc' dependency"
        ) from error
    return RTCPeerConnection, RTCSessionDescription, (
        RTCConfiguration,
        RTCIceServer,
        RTCIceCandidate,
    )


def _new_peer_connection(ice_servers: tuple[str, ...]) -> Any:
    RTCPeerConnection, _, configuration_types = _load_aiortc()
    RTCConfiguration, RTCIceServer, _ = configuration_types
    configuration = RTCConfiguration(
        iceServers=[RTCIceServer(urls=url) for url in ice_servers]
    )
    return RTCPeerConnection(configuration=configuration)


async def _create_offer(peer_connection: Any) -> Any:
    offer = await peer_connection.createOffer()
    await peer_connection.setLocalDescription(offer)
    return peer_connection.localDescription


async def _create_answer(peer_connection: Any) -> Any:
    answer = await peer_connection.createAnswer()
    await peer_connection.setLocalDescription(answer)
    return peer_connection.localDescription


async def _set_remote_description(
    peer_connection: Any, description_type: str, sdp: str
) -> None:
    _, RTCSessionDescription, _ = _load_aiortc()
    await peer_connection.setRemoteDescription(
        RTCSessionDescription(sdp=sdp, type=description_type)
    )


def _create_data_channel(
    peer_connection: Any,
    label: str,
    negotiated: bool,
    channel_id: int | None,
) -> Any:
    options: dict[str, Any] = {"negotiated": negotiated}
    if channel_id is not None:
        options["id"] = channel_id
    return peer_connection.createDataChannel(label, **options)


async def _add_ice_candidate(peer_connection: Any, candidate: Any) -> None:
    await peer_connection.addIceCandidate(candidate)


async def _add_ice_candidate_data(
    peer_connection: Any, candidate_data: dict[str, Any]
) -> None:
    _, _, configuration_types = _load_aiortc()
    RTCIceCandidate = configuration_types[2]
    candidate = _candidate_from_data(candidate_data, RTCIceCandidate)
    await peer_connection.addIceCandidate(candidate)


def _candidate_from_data(candidate_data: dict[str, Any], candidate_type: Any) -> Any:
    """Build aiortc's candidate object from the browser JSON representation."""
    candidate_sdp = candidate_data.get("candidate")
    if not isinstance(candidate_sdp, str):
        raise ValueError("ICE candidate data requires a candidate string")
    if not candidate_sdp:
        return None
    parts = candidate_sdp.removeprefix("candidate:").split()
    if len(parts) < 8 or parts[6] != "typ":
        raise ValueError("invalid ICE candidate SDP")
    values: dict[str, Any] = {
        "foundation": parts[0],
        "component": int(parts[1]),
        "protocol": parts[2].lower(),
        "priority": int(parts[3]),
        "ip": parts[4],
        "port": int(parts[5]),
        "type": parts[7],
        "sdpMid": candidate_data.get("sdpMid"),
        "sdpMLineIndex": candidate_data.get("sdpMLineIndex"),
        "usernameFragment": candidate_data.get("usernameFragment"),
    }
    attributes = dict(zip(parts[8::2], parts[9::2]))
    values["relatedAddress"] = attributes.get("raddr")
    values["relatedPort"] = (
        int(attributes["rport"]) if "rport" in attributes else None
    )
    values["tcpType"] = attributes.get("tcptype")
    try:
        return candidate_type(**values)
    except (TypeError, ValueError) as error:
        raise ValueError("invalid ICE candidate fields") from error


def _register_message_handler(channel: Any, handler: Any) -> None:
    channel.on("message", handler)


def _register_data_channel_handler(peer_connection: Any, handler: Any) -> None:
    peer_connection.on("datachannel", handler)


def _register_ice_candidate_handler(peer_connection: Any, handler: Any) -> None:
    peer_connection.on("icecandidate", handler)
