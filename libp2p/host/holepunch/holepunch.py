from collections.abc import Iterable
import logging

from google.protobuf.message import DecodeError
from multiaddr import Multiaddr

from libp2p.custom_types import TProtocol
from libp2p.host.basic_host import BasicHost
from libp2p.host.holepunch.pb.holepunch_pb2 import HolePunch
from libp2p.io.utils import read_exactly
from libp2p.peer.id import ID
from libp2p.utils.varint import decode_uvarint_from_stream, encode_varint_prefixed

HOLEPUNCH_PROTOCOL_ID = TProtocol("/libp2p/dcutr")
MAX_MESSAGE_SIZE = 4096

logger = logging.getLogger("libp2p.host.holepunch")


class HolePunchProtocolError(ValueError):
    pass


class HolePunchService:
    """
    DCUtR coordination and candidate-address exchange.

    Direct dialing is deliberately kept outside this service until the swarm
    supports replacing a relayed connection atomically.
    """

    def __init__(self, host: BasicHost) -> None:
        self.host = host
        host.set_stream_handler(HOLEPUNCH_PROTOCOL_ID, self.handle_stream)

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
        length = await decode_uvarint_from_stream(stream)
        if length > MAX_MESSAGE_SIZE:
            raise HolePunchProtocolError("DCUtR message exceeds 4 KiB")
        message = HolePunch()
        try:
            message.ParseFromString(await read_exactly(stream, length))
        except DecodeError as error:
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
        return tuple(
            address
            for address in addresses
            if not any(
                protocol.name == "p2p-circuit" for protocol in address.protocols()
            )
        )

    async def handle_stream(self, stream) -> None:
        try:
            connect = await self._read_message(stream)
            if connect.type != HolePunch.CONNECT:
                raise HolePunchProtocolError("expected DCUtR CONNECT")
            await stream.write(
                self._message(HolePunch.CONNECT, self._candidate_addrs())
            )
            sync = await self._read_message(stream)
            if sync.type != HolePunch.SYNC:
                raise HolePunchProtocolError("expected DCUtR SYNC")
        except (HolePunchProtocolError, EOFError) as error:
            logger.debug("invalid DCUtR stream: %s", error)
        finally:
            await stream.close()

    async def connect(
        self, peer_id: ID, addresses: Iterable[Multiaddr] | None = None
    ) -> tuple[Multiaddr, ...]:
        """Exchange DCUtR candidates over an existing connection."""
        stream = await self.host.new_stream(peer_id, [HOLEPUNCH_PROTOCOL_ID])
        try:
            await stream.write(
                self._message(
                    HolePunch.CONNECT,
                    self._candidate_addrs() if addresses is None else addresses,
                )
            )
            response = await self._read_message(stream)
            if response.type != HolePunch.CONNECT:
                raise HolePunchProtocolError("expected DCUtR CONNECT response")
            remote_addresses = self._addresses(response)
            await stream.write(self._message(HolePunch.SYNC, ()))
            direct_addresses = self._direct_addresses(remote_addresses)
            dial_peer_direct = getattr(
                self.host.get_network(), "dial_peer_direct", None
            )
            if direct_addresses and dial_peer_direct is not None:
                await dial_peer_direct(peer_id, direct_addresses)
            return remote_addresses
        finally:
            await stream.close()
