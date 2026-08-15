from collections.abc import Mapping, Sequence
import logging

from google.protobuf.message import (
    DecodeError,
)
from multiaddr import Multiaddr
import trio

from libp2p.custom_types import (
    TProtocol,
)
from libp2p.host.autonat.pb.autonat_pb2 import (
    Message,
)
from libp2p.host.basic_host import (
    BasicHost,
)
from libp2p.io.utils import read_exactly
from libp2p.network.stream.net_stream import (
    NetStream,
)
from libp2p.peer.id import (
    ID,
)
from libp2p.peer.peerstore import (
    IPeerStore,
)
from libp2p.utils.varint import (
    decode_uvarint_from_stream,
    encode_varint_prefixed,
    read_varint_prefixed_bytes,
)

AUTONAT_PROTOCOL_ID = TProtocol("/libp2p/autonat/1.0.0")
AUTONAT_MIN_RESPONSES = 4
MAX_AUTONAT_MESSAGE_SIZE = 4096
MAX_CONCURRENT_DIALS = 4

logger = logging.getLogger("libp2p.host.autonat")


class AutoNATStatus:
    """
    AutoNAT Status Enumeration.

    Defines the possible states of NAT traversal for a libp2p node:
    - UNKNOWN (0): Initial state, NAT status not yet determined
    - PUBLIC (1): Node is publicly reachable from the internet
    - PRIVATE (2): Node is behind NAT, not directly reachable
    """

    UNKNOWN = 0
    PUBLIC = 1
    PRIVATE = 2


class AutoNATService:
    """
    AutoNAT Service Implementation.

    A service that helps libp2p nodes determine their NAT status by
    attempting to establish connections with other peers. The service
    maintains a record of dial attempts and their results to classify
    the node as either public or private.
    """

    def __init__(self, host: BasicHost) -> None:
        """
        Create a new AutoNAT service instance.

        Parameters
        ----------
        host : BasicHost
            The libp2p host instance that provides networking capabilities
            for the AutoNAT service, including peer discovery and connection
            management.

        """
        self.host = host
        self.peerstore: IPeerStore = host.get_peerstore()
        self.status = AutoNATStatus.UNKNOWN
        self.dial_results: dict[ID, bool] = {}
        self.observed_addrs: set[Multiaddr] = set()
        self._dial_limiter = trio.CapacityLimiter(MAX_CONCURRENT_DIALS)
        host.set_stream_handler(AUTONAT_PROTOCOL_ID, self.handle_stream)

    async def handle_stream(self, stream: NetStream) -> None:
        """
        Process an incoming AutoNAT stream.

        Parameters
        ----------
        stream : NetStream
            The network stream to handle for AutoNAT protocol communication.

        """
        try:
            request_bytes = await self._read_message(stream)
            request = Message()
            try:
                request.ParseFromString(request_bytes)
            except DecodeError:
                response = Message(type=Message.DIAL_RESPONSE)
                response.dialResponse.status = Message.E_BAD_REQUEST
                await stream.write(encode_varint_prefixed(response.SerializeToString()))
                return
            remote_address = stream.get_remote_address()
            if request.type == Message.DIAL and remote_address is None:
                response = Message(type=Message.DIAL_RESPONSE)
                response.dialResponse.status = Message.E_DIAL_REFUSED
            else:
                response = await self._handle_request(request, remote_address)
            await stream.write(encode_varint_prefixed(response.SerializeToString()))
        except ValueError:
            response = Message(type=Message.DIAL_RESPONSE)
            response.dialResponse.status = Message.E_BAD_REQUEST
            await stream.write(encode_varint_prefixed(response.SerializeToString()))
        except Exception as e:
            logger.error("Error handling AutoNAT stream: %s", str(e))
        finally:
            await stream.close()

    async def _handle_request(
        self,
        request: bytes | Message,
        remote_address: tuple[str, int] | None = None,
    ) -> Message:
        """
        Process an AutoNAT protocol request.

        Parameters
        ----------
        request : Union[bytes, Message]
            The request data to be processed, either as raw bytes or a
            pre-parsed Message object.
        remote_address : tuple[str, int] | None
            The observed network address of the requesting peer, when
            available.

        Returns
        -------
        Message
            The response message containing the result of processing the
            request. Returns an error response if the request type is not
            recognized.

        """
        if isinstance(request, bytes):
            message = Message()
            message.ParseFromString(request)
        else:
            message = request

        if message.type == Message.DIAL:
            response = await self._handle_dial(message, remote_address)
            return response

        # Handle unknown request type
        response = Message(type=Message.DIAL_RESPONSE)
        response.dialResponse.status = Message.E_BAD_REQUEST
        return response

    async def _handle_dial(
        self,
        message: Message,
        remote_address: tuple[str, int] | None = None,
    ) -> Message:
        """
        Process an AutoNAT dial request.

        Parameters
        ----------
        message : Message
            The dial request message containing peer information to test
            connectivity.
        remote_address : tuple[str, int] | None
            The observed network address of the requesting peer, when
            available.

        Returns
        -------
        Message
            The response message containing the results of the dial
            attempts, including success/failure status for each peer.

        """
        response = Message(type=Message.DIAL_RESPONSE)
        if not message.HasField("dial") or not message.dial.HasField("peer"):
            response.dialResponse.status = Message.E_BAD_REQUEST
            return response

        peer = message.dial.peer
        if not peer.id:
            response.dialResponse.status = Message.E_BAD_REQUEST
            return response
        peer_id = ID(peer.id)
        addresses: list[Multiaddr] = []
        for raw_addr in peer.addrs:
            try:
                address = Multiaddr(raw_addr)
                if remote_address is not None:
                    address_ip = (
                        address.value_for_protocol("ip4")
                        or address.value_for_protocol("ip6")
                    )
                    if address_ip != remote_address[0]:
                        continue
                addresses.append(address)
            except (TypeError, ValueError):
                logger.debug("ignoring invalid AutoNAT address for %s", peer_id)
        if not addresses and remote_address is not None:
            response.dialResponse.status = Message.E_DIAL_REFUSED
            return response
        if addresses:
            self.peerstore.add_addrs(peer_id, addresses, 60_000)
        async with self._dial_limiter:
            success = await self._try_dial(peer_id)
        self.dial_results[peer_id] = success
        response.dialResponse.status = Message.OK if success else Message.E_DIAL_ERROR
        if success and addresses:
            response.dialResponse.addr = addresses[0].to_bytes()
        return response

    async def _try_dial(self, peer_id: ID) -> bool:
        """
        Attempt to establish a connection with a peer.

        Parameters
        ----------
        peer_id : ID
            The identifier of the peer to attempt to dial.

        Returns
        -------
        bool
            True if the connection was successfully established,
            False if the connection attempt failed.

        """
        try:
            stream = await self.host.new_stream(peer_id, [AUTONAT_PROTOCOL_ID])
            await stream.close()
            return True
        except Exception:
            return False

    async def _read_message(self, stream: NetStream) -> bytes:
        """Read one bounded length-delimited AutoNAT message."""
        message_length = await decode_uvarint_from_stream(stream)
        if message_length > MAX_AUTONAT_MESSAGE_SIZE:
            raise ValueError("AutoNAT message exceeds maximum size")
        return await read_exactly(stream, message_length)

    def get_status(self) -> int:
        """
        Retrieve the current AutoNAT status.

        Returns
        -------
        int
            The current NAT status:
            - AutoNATStatus.UNKNOWN (0): Status not yet determined
            - AutoNATStatus.PUBLIC (1): Node is publicly reachable
            - AutoNATStatus.PRIVATE (2): Node is behind NAT

        """
        return self.status

    async def probe(
        self, server_peer_id: ID, addresses: Sequence[Multiaddr]
    ) -> bool:
        """Ask an AutoNAT server to dial this node's advertised addresses."""
        request = Message(type=Message.DIAL)
        request_peer = request.dial.peer
        request_peer.id = self.host.get_id().to_bytes()
        request_peer.addrs.extend(address.to_bytes() for address in addresses)

        stream = await self.host.new_stream(server_peer_id, [AUTONAT_PROTOCOL_ID])
        try:
            await stream.write(encode_varint_prefixed(request.SerializeToString()))
            response = Message()
            response.ParseFromString(await read_varint_prefixed_bytes(stream))
            success = response.type == Message.DIAL_RESPONSE and (
                response.dialResponse.status == Message.OK
            )
            if success and response.dialResponse.addr:
                try:
                    observed_addr = Multiaddr(response.dialResponse.addr)
                except (TypeError, ValueError):
                    logger.debug("Ignoring invalid AutoNAT observed address")
                else:
                    self.observed_addrs.add(observed_addr)
                    self.peerstore.add_addrs(
                        self.host.get_id(), [observed_addr], 60_000
                    )
            self.dial_results[server_peer_id] = success
            self.update_status()
            return success
        finally:
            await stream.close()

    async def probe_many(
        self,
        probes: Mapping[ID, Sequence[Multiaddr]],
    ) -> dict[ID, bool]:
        """
        Probe multiple independent AutoNAT servers concurrently.

        Failed individual probes are recorded as failures without preventing
        other servers from contributing to the reachability result.
        """
        results: dict[ID, bool] = {}

        async def run_probe(
            server_peer_id: ID, addresses: Sequence[Multiaddr]
        ) -> None:
            try:
                results[server_peer_id] = await self.probe(server_peer_id, addresses)
            except Exception:
                logger.debug(
                    "AutoNAT probe failed for server %s",
                    server_peer_id,
                    exc_info=True,
                )
                self.dial_results[server_peer_id] = False
                self.update_status()
                results[server_peer_id] = False

        async with trio.open_nursery() as nursery:
            for server_peer_id, addresses in probes.items():
                nursery.start_soon(run_probe, server_peer_id, addresses)

        return results

    def update_status(self) -> None:
        """
        Update the AutoNAT status based on dial results.

        Analyzes the accumulated dial attempt results to determine if the
        node is publicly reachable. The node is considered public or private
        only after more than three distinct peers report the same result.
        """
        if not self.dial_results:
            self.status = AutoNATStatus.UNKNOWN
            return

        success_count = sum(1 for success in self.dial_results.values() if success)
        failure_count = len(self.dial_results) - success_count
        if success_count >= AUTONAT_MIN_RESPONSES:
            self.status = AutoNATStatus.PUBLIC
        elif failure_count >= AUTONAT_MIN_RESPONSES:
            self.status = AutoNATStatus.PRIVATE
        else:
            self.status = AutoNATStatus.UNKNOWN
