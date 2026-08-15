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

    async def create_data_channel(self, connection_role: bool) -> WebRTCConnection:
        """Create the empty-label libp2p data channel and adapt it to Trio."""
        peer_connection = self._require_peer_connection()
        channel = await self.bridge.call(_create_data_channel, peer_connection)
        connection = WebRTCConnection(
            channel,
            self.bridge.call,
            is_initiator=connection_role,
        )
        await self.bridge.call(
            _register_message_handler, channel, connection.on_message
        )
        return connection

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
            RTCIceServer,
            RTCPeerConnection,
            RTCSessionDescription,
        )
    except ImportError as error:
        raise WebRTCDependencyError(
            "WebRTC support requires the optional 'aiortc' dependency"
        ) from error
    return RTCPeerConnection, RTCSessionDescription, (RTCConfiguration, RTCIceServer)


def _new_peer_connection(ice_servers: tuple[str, ...]) -> Any:
    RTCPeerConnection, _, configuration_types = _load_aiortc()
    RTCConfiguration, RTCIceServer = configuration_types
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


def _create_data_channel(peer_connection: Any) -> Any:
    return peer_connection.createDataChannel("")


def _register_message_handler(channel: Any, handler: Any) -> None:
    channel.on("message", handler)
