from collections.abc import Iterable
import logging

from google.protobuf.message import DecodeError
from multiaddr import Multiaddr
import trio

from libp2p.custom_types import TProtocol
from libp2p.exceptions import ParseError
from libp2p.host.basic_host import BasicHost
from libp2p.host.holepunch.pb.holepunch_pb2 import HolePunch
from libp2p.io.exceptions import IncompleteReadError
from libp2p.io.utils import read_exactly
from libp2p.network.events import EventConnected
from libp2p.peer.id import ID
from libp2p.utils.varint import decode_uvarint_from_stream, encode_varint_prefixed

HOLEPUNCH_PROTOCOL_ID = TProtocol("/libp2p/dcutr")
MAX_MESSAGE_SIZE = 4096
MAX_ATTEMPTS = 3
MAX_SYNC_DELAY = 5
STREAM_TIMEOUT = 60

logger = logging.getLogger("libp2p.host.holepunch")


class HolePunchProtocolError(ValueError):
    pass


class HolePunchActiveError(HolePunchProtocolError):
    pass


class HolePunchService:
    """
    DCUtR coordination and candidate-address exchange.

    Direct dialing is delegated to the swarm, which owns connection replacement.
    """

    def __init__(self, host: BasicHost) -> None:
        self.host = host
        self._upgrading: set[ID] = set()
        host.set_stream_handler(HOLEPUNCH_PROTOCOL_ID, self.handle_stream)

    @staticmethod
    def _is_relayed_connection(connection) -> bool:
        address = getattr(connection, "get_remote_multiaddr", lambda: None)()
        return address is not None and any(
            protocol.name == "p2p-circuit" for protocol in address.protocols()
        )

    async def run(self) -> None:
        """Upgrade newly established relay connections in the background."""
        subscription = await self.host.get_network().get_event_bus().subscribe(
            EventConnected, max_buffer_size=64
        )
        try:
            async with trio.open_nursery() as nursery:
                async for event in subscription:
                    peer_id = event.conn.muxed_conn.peer_id
                    if not self._is_relayed_connection(event.conn):
                        continue
                    if peer_id in self._upgrading:
                        continue
                    nursery.start_soon(self._upgrade, peer_id)
        finally:
            await subscription.unsubscribe()

    async def _upgrade(self, peer_id: ID) -> None:
        try:
            await self.connect(peer_id)
        except Exception as error:
            logger.debug("DCUtR upgrade failed for peer %s", peer_id, exc_info=error)

    def _candidate_addrs(self) -> tuple[Multiaddr, ...]:
        addresses: set[Multiaddr] = set(self.host.get_addrs())
        autonat = getattr(self.host, "autonat", None)
        if autonat is not None:
            addresses.update(autonat.observed_addrs)
        return tuple(addresses)

    @staticmethod
    def _message(message_type: int, addresses: Iterable[Multiaddr]) -> bytes:
        message = HolePunch(type=message_type)
        message.ObsAddrs.extend(address.to_bytes() for address in addresses)
        encoded = message.SerializeToString()
        if len(encoded) > MAX_MESSAGE_SIZE:
            raise HolePunchProtocolError("DCUtR message exceeds 4 KiB")
        return encode_varint_prefixed(encoded)

    @staticmethod
    async def _read_message(stream) -> HolePunch:
        try:
            length = await decode_uvarint_from_stream(stream)
        except (IncompleteReadError, ParseError, ValueError) as error:
            raise HolePunchProtocolError("invalid DCUtR length prefix") from error
        if length > MAX_MESSAGE_SIZE:
            raise HolePunchProtocolError("DCUtR message exceeds 4 KiB")
        message = HolePunch()
        try:
            message.ParseFromString(await read_exactly(stream, length))
        except (DecodeError, IncompleteReadError) as error:
            raise HolePunchProtocolError("invalid DCUtR message") from error
        if not message.IsInitialized():
            raise HolePunchProtocolError("DCUtR message has no type")
        return message

    @staticmethod
    def _addresses(message: HolePunch) -> tuple[Multiaddr, ...]:
        addresses: list[Multiaddr] = []
        for raw_address in message.ObsAddrs:
            try:
                addresses.append(Multiaddr(raw_address))
            except ValueError as error:
                raise HolePunchProtocolError("invalid DCUtR multiaddr") from error
        return tuple(addresses)

    @staticmethod
    def _direct_addresses(addresses: Iterable[Multiaddr]) -> tuple[Multiaddr, ...]:
        direct: list[Multiaddr] = []
        seen: set[Multiaddr] = set()
        for address in addresses:
            if address in seen or any(
                protocol.name == "p2p-circuit" for protocol in address.protocols()
            ):
                continue
            seen.add(address)
            direct.append(address)
        return tuple(direct)

    async def handle_stream(self, stream) -> None:
        try:
            with trio.fail_after(STREAM_TIMEOUT):
                connect = await self._read_message(stream)
                if connect.type != HolePunch.CONNECT:
                    raise HolePunchProtocolError("expected DCUtR CONNECT")
                remote_addresses = self._addresses(connect)
                await stream.write(
                    self._message(HolePunch.CONNECT, self._candidate_addrs())
                )
                sync = await self._read_message(stream)
                if sync.type != HolePunch.SYNC:
                    raise HolePunchProtocolError("expected DCUtR SYNC")
                direct_addresses = self._direct_addresses(remote_addresses)
                dial_peer_direct = getattr(
                    self.host.get_network(), "dial_peer_direct", None
                )
                peer_id = stream.muxed_conn.peer_id
                if direct_addresses and dial_peer_direct is not None:
                    await dial_peer_direct(peer_id, direct_addresses)
        except (HolePunchProtocolError, EOFError, trio.TooSlowError) as error:
            logger.debug("invalid DCUtR stream: %s", error)
        finally:
            await stream.close()

    async def connect(
        self, peer_id: ID, addresses: Iterable[Multiaddr] | None = None
    ) -> tuple[Multiaddr, ...]:
        if peer_id in self._upgrading:
            raise HolePunchActiveError(f"DCUtR upgrade already active for {peer_id}")
        self._upgrading.add(peer_id)
        try:
            return await self._connect_attempts(peer_id, addresses)
        finally:
            self._upgrading.discard(peer_id)

    async def _connect_attempts(
        self, peer_id: ID, addresses: Iterable[Multiaddr] | None = None
    ) -> tuple[Multiaddr, ...]:
        """Exchange DCUtR candidates over an existing connection."""
        local_addresses = (
            self._candidate_addrs() if addresses is None else tuple(addresses)
        )
        last_error: Exception | None = None
        for attempt in range(MAX_ATTEMPTS):
            stream = await self.host.new_stream(peer_id, [HOLEPUNCH_PROTOCOL_ID])
            try:
                with trio.fail_after(STREAM_TIMEOUT):
                    started_at = trio.current_time()
                    await stream.write(
                        self._message(HolePunch.CONNECT, local_addresses)
                    )
                    response = await self._read_message(stream)
                    if response.type != HolePunch.CONNECT:
                        raise HolePunchProtocolError(
                            "expected DCUtR CONNECT response"
                        )
                    remote_addresses = self._addresses(response)
                    await stream.write(self._message(HolePunch.SYNC, ()))
                    direct_addresses = self._direct_addresses(remote_addresses)
                    dial_peer_direct = getattr(
                        self.host.get_network(), "dial_peer_direct", None
                    )
                    if direct_addresses and dial_peer_direct is not None:
                        await trio.sleep(
                            min(
                                (trio.current_time() - started_at) / 2,
                                MAX_SYNC_DELAY,
                            )
                        )
                        await dial_peer_direct(peer_id, direct_addresses)
                    return remote_addresses
            except Exception as error:
                last_error = error
                logger.debug(
                    "DCUtR attempt %d/%d failed for peer %s",
                    attempt + 1,
                    MAX_ATTEMPTS,
                    peer_id,
                    exc_info=error,
                )
                if attempt + 1 == MAX_ATTEMPTS:
                    raise
            finally:
                await stream.close()

        raise HolePunchProtocolError("DCUtR attempts exhausted") from last_error
