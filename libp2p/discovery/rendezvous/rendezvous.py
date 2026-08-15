"""Trio-native rendezvous point and client."""

from dataclasses import dataclass
import logging
import time
from typing import Any

from libp2p.custom_types import TProtocol
from libp2p.discovery.events.peerDiscovery import peerDiscovery
from libp2p.io.exceptions import IncompleteReadError
from libp2p.io.utils import read_exactly
from libp2p.peer.envelope import consume_envelope
from libp2p.peer.peerinfo import PeerInfo
from libp2p.utils.varint import decode_uvarint_from_stream, encode_varint_prefixed

from .pb.rendezvous_pb2 import Message

PROTOCOL_ID = TProtocol("/rendezvous/1.0.0")
MAX_MESSAGE_SIZE = 64 * 1024
DEFAULT_TTL = 2 * 60 * 60
MAX_TTL = 72 * 60 * 60
MAX_LIMIT = 1000
COOKIE_SIZE = 16
PEER_RECORD_DOMAIN = "libp2p-peer-record"

logger = logging.getLogger("libp2p.discovery.rendezvous")


class RendezvousProtocolError(ValueError):
    """Raised for malformed rendezvous requests or error responses."""


@dataclass
class Registration:
    namespace: str
    peer_id: Any
    signed_peer_record: bytes
    expires_at: float
    generation: int


async def _read_message(stream) -> Message:
    try:
        length = await decode_uvarint_from_stream(stream)
        if length > MAX_MESSAGE_SIZE:
            raise RendezvousProtocolError("rendezvous message exceeds 64 KiB")
        raw = await read_exactly(stream, length)
    except IncompleteReadError as error:
        raise RendezvousProtocolError("truncated rendezvous message") from error
    message = Message()
    try:
        message.ParseFromString(raw)
    except Exception as error:
        raise RendezvousProtocolError("invalid rendezvous message") from error
    if not message.HasField("type"):
        raise RendezvousProtocolError("rendezvous message has no type")
    return message


async def _write_message(stream, message: Message) -> None:
    encoded = message.SerializeToString()
    if len(encoded) > MAX_MESSAGE_SIZE:
        raise RendezvousProtocolError("rendezvous message exceeds 64 KiB")
    await stream.write(encode_varint_prefixed(encoded))


def _status_response(status: int, text: str) -> Message:
    return Message(
        type=Message.DISCOVER_RESPONSE,
        discoverResponse=Message.DiscoverResponse(
            status=status,
            statusText=text,
        ),
    )


class RendezvousPoint:
    """Store signed peer records and serve rendezvous protocol streams."""

    def __init__(self, host: Any) -> None:
        self.host = host
        self._registrations: dict[tuple[str, Any], Registration] = {}
        self._generation = 0
        host.set_stream_handler(PROTOCOL_ID, self.handle_stream)

    async def handle_stream(self, stream) -> None:
        try:
            while True:
                message = await _read_message(stream)
                response = self._handle_message(message, stream)
                if response is not None:
                    await _write_message(stream, response)
        except (RendezvousProtocolError, IncompleteReadError) as error:
            logger.debug("rendezvous stream closed: %s", error)
        finally:
            await stream.close()

    def _handle_message(self, message: Message, stream) -> Message | None:
        if message.type == Message.REGISTER:
            return self._register(message, stream)
        if message.type == Message.UNREGISTER:
            self._unregister(message, stream)
            return None
        if message.type == Message.DISCOVER:
            return self._discover(message)
        return _status_response(Message.E_INTERNAL_ERROR, "unsupported message type")

    def _register(self, message: Message, stream) -> Message:
        if not message.HasField("register") or not message.register.ns:
            return _register_response(Message.E_INVALID_NAMESPACE, "namespace required")
        request = message.register
        if len(request.ns.encode()) > 255:
            return _register_response(Message.E_INVALID_NAMESPACE, "namespace too long")
        if not request.HasField("signedPeerRecord"):
            return _register_response(
                Message.E_INVALID_SIGNED_PEER_RECORD,
                "signed peer record required",
            )
        ttl = request.ttl if request.HasField("ttl") else DEFAULT_TTL
        if ttl <= 0 or ttl > MAX_TTL:
            return _register_response(Message.E_INVALID_TTL, "invalid TTL")
        try:
            _, record = consume_envelope(
                request.signedPeerRecord, PEER_RECORD_DOMAIN
            )
        except Exception as error:
            logger.debug("invalid rendezvous peer record: %s", error)
            return _register_response(
                Message.E_INVALID_SIGNED_PEER_RECORD,
                "invalid signed peer record",
            )
        peer_id = getattr(stream.muxed_conn, "peer_id", record.peer_id)
        if record.peer_id != peer_id:
            return _register_response(
                Message.E_INVALID_SIGNED_PEER_RECORD,
                "peer record does not match stream peer",
            )
        self._generation += 1
        self._registrations[(request.ns, peer_id)] = Registration(
            request.ns,
            peer_id,
            request.signedPeerRecord,
            time.time() + ttl,
            self._generation,
        )
        return _register_response(Message.OK, "", ttl)

    def _unregister(self, message: Message, stream) -> None:
        if not message.HasField("unregister"):
            return
        peer_id = stream.muxed_conn.peer_id
        self._registrations.pop((message.unregister.ns, peer_id), None)

    def _discover(self, message: Message) -> Message:
        request = (
            message.discover
            if message.HasField("discover")
            else Message.Discover()
        )
        self._expire()
        limit = request.limit if request.HasField("limit") else MAX_LIMIT
        limit = min(max(limit, 1), MAX_LIMIT)
        cursor = request.cookie if request.HasField("cookie") else b""
        generation = int.from_bytes(cursor, "big") if cursor else 0
        registrations = [
            registration
            for registration in self._registrations.values()
            if (not request.ns or registration.namespace == request.ns)
            and registration.generation > generation
        ]
        registrations.sort(key=lambda registration: registration.generation)
        registrations = registrations[:limit]
        response = Message.DiscoverResponse(cookie=self._generation.to_bytes(8, "big"))
        for registration in registrations:
            response.registrations.add(
                ns=registration.namespace,
                signedPeerRecord=registration.signed_peer_record,
                ttl=max(1, int(registration.expires_at - time.time())),
            )
        return Message(type=Message.DISCOVER_RESPONSE, discoverResponse=response)

    def _expire(self) -> None:
        now = time.time()
        for key, registration in tuple(self._registrations.items()):
            if registration.expires_at <= now:
                del self._registrations[key]


def _register_response(status: int, text: str, ttl: int | None = None) -> Message:
    response = Message.RegisterResponse(status=status, statusText=text)
    if ttl is not None:
        response.ttl = ttl
    return Message(type=Message.REGISTER_RESPONSE, registerResponse=response)


class RendezvousClient:
    """Client operations for a remote rendezvous point."""

    def __init__(self, host: Any) -> None:
        self.host = host

    async def register(
        self,
        peer_id: Any,
        namespace: str,
        signed_peer_record: bytes,
        ttl: int = DEFAULT_TTL,
    ) -> int:
        response = await self._request(
            peer_id,
            Message(
                type=Message.REGISTER,
                register=Message.Register(
                    ns=namespace,
                    signedPeerRecord=signed_peer_record,
                    ttl=ttl,
                ),
            ),
        )
        if response.type != Message.REGISTER_RESPONSE:
            raise RendezvousProtocolError("expected register response")
        result = response.registerResponse
        if result.status != Message.OK:
            raise RendezvousProtocolError(result.statusText)
        return result.ttl

    async def unregister(self, peer_id: Any, namespace: str) -> None:
        stream = await self.host.new_stream(peer_id, [PROTOCOL_ID])
        try:
            await _write_message(
                stream,
                Message(
                    type=Message.UNREGISTER,
                    unregister=Message.Unregister(ns=namespace),
                ),
            )
        finally:
            await stream.close()

    async def discover(
        self,
        peer_id: Any,
        namespace: str = "",
        limit: int = MAX_LIMIT,
        cookie: bytes = b"",
    ) -> tuple[tuple[PeerInfo, ...], bytes]:
        response = await self._request(
            peer_id,
            Message(
                type=Message.DISCOVER,
                discover=Message.Discover(ns=namespace, limit=limit, cookie=cookie),
            ),
        )
        if response.type != Message.DISCOVER_RESPONSE:
            raise RendezvousProtocolError("expected discover response")
        result = response.discoverResponse
        if result.status != Message.OK:
            raise RendezvousProtocolError(result.statusText)
        registrations: list[PeerInfo] = []
        for registration in result.registrations:
            try:
                _, record = consume_envelope(
                    registration.signedPeerRecord,
                    PEER_RECORD_DOMAIN,
                )
            except Exception as error:
                raise RendezvousProtocolError(
                    "discover response contains an invalid peer record"
                ) from error
            peer_info = PeerInfo(record.peer_id, record.addrs)
            registrations.append(peer_info)
            peerDiscovery.emit_peer_discovered(peer_info)
        return tuple(registrations), result.cookie

    async def _request(self, peer_id: Any, message: Message) -> Message:
        stream = await self.host.new_stream(peer_id, [PROTOCOL_ID])
        try:
            await _write_message(stream, message)
            return await _read_message(stream)
        finally:
            await stream.close()
