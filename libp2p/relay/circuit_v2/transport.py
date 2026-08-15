"""
Transport implementation for Circuit Relay v2.

This module implements the transport layer for Circuit Relay v2,
allowing peers to establish connections through relay nodes.
"""

from collections.abc import Awaitable, Callable
import logging
import time

import multiaddr
import trio

from libp2p.abc import (
    IHost,
    IListener,
    INetStream,
    ITransport,
    ReadWriteCloser,
)
from libp2p.network.connection.raw_connection import (
    RawConnection,
)
from libp2p.peer.id import (
    ID,
)
from libp2p.peer.peerinfo import (
    PeerInfo,
)
from libp2p.tools.async_service import (
    Service,
)

from .config import (
    ClientConfig,
    RelayConfig,
)
from .discovery import (
    RelayDiscovery,
)
from .framing import (
    encode_message,
    read_message,
)
from .pb.circuit_pb2 import (
    HopMessage,
    Peer,
    StopMessage,
)
from .protocol import (
    PROTOCOL_ID,
    CircuitV2Protocol,
)
from .protocol_buffer import (
    StatusCode,
)

logger = logging.getLogger("libp2p.relay.circuit_v2.transport")


def _valid_multiaddr(raw_addr: bytes) -> bool:
    """Return whether a reservation address can be parsed as a multiaddr."""
    try:
        multiaddr.Multiaddr(raw_addr)
    except (TypeError, ValueError):
        return False
    return True


class CircuitV2Transport(ITransport):
    """
    CircuitV2Transport implements the transport interface for Circuit Relay v2.

    This transport allows peers to establish connections through relay nodes
    when direct connections are not possible.
    """

    def __init__(
        self,
        host: IHost,
        protocol: CircuitV2Protocol,
        config: RelayConfig,
    ) -> None:
        """
        Initialize the Circuit v2 transport.

        Parameters
        ----------
        host : IHost
            The libp2p host this transport is running on
        protocol : CircuitV2Protocol
            The Circuit v2 protocol instance
        config : RelayConfig
            Relay configuration

        """
        self.host = host
        self.protocol = protocol
        self.config = config
        self.client_config = ClientConfig()
        self.discovery = RelayDiscovery(
            host=host,
            auto_reserve=config.enable_client,
            discovery_interval=config.discovery_interval,
            max_relays=config.max_relays,
        )
        self._reservation_streams: dict[ID, INetStream] = {}

    async def dial(
        self,
        maddr: multiaddr.Multiaddr,
    ) -> RawConnection:
        """
        Dial a peer using the multiaddr.

        Parameters
        ----------
        maddr : multiaddr.Multiaddr
            The multiaddr to dial

        Returns
        -------
        RawConnection
            The established connection

        Raises
        ------
        ConnectionError
            If the connection cannot be established

        """
        parts = maddr.split()
        circuit_index = next(
            (
                index
                for index, part in enumerate(parts)
                if any(protocol.name == "p2p-circuit" for protocol in part.protocols())
            ),
            None,
        )
        if circuit_index is None:
            peer_id_str = maddr.value_for_protocol("p2p")
            if not peer_id_str:
                raise ConnectionError("Multiaddr does not contain peer ID")
            peer_id = ID.from_base58(peer_id_str)
            peer_info = PeerInfo(peer_id, [maddr])
            return await self.dial_peer_info(peer_info)

        if circuit_index == 0 or circuit_index + 1 >= len(parts):
            raise ConnectionError("Invalid circuit relay multiaddr")
        relay_addr = multiaddr.Multiaddr.join(*parts[:circuit_index])
        relay_peer_id = ID.from_base58(
            parts[circuit_index - 1].value_for_protocol("p2p")
        )
        target_peer_id = ID.from_base58(
            parts[circuit_index + 1].value_for_protocol("p2p")
        )
        self.host.get_peerstore().add_addrs(relay_peer_id, [relay_addr], 60_000)
        peer_info = PeerInfo(target_peer_id, [maddr])

        # Use the internal dial_peer_info method
        return await self.dial_peer_info(peer_info, relay_peer_id=relay_peer_id)

    async def dial_peer_info(
        self,
        peer_info: PeerInfo,
        *,
        relay_peer_id: ID | None = None,
    ) -> RawConnection:
        """
        Dial a peer through a relay.

        Parameters
        ----------
        peer_info : PeerInfo
            The peer to dial
        relay_peer_id : Optional[ID], optional
            Optional specific relay peer to use

        Returns
        -------
        RawConnection
            The established connection

        Raises
        ------
        ConnectionError
            If the connection cannot be established

        """
        # If no specific relay is provided, try to find one
        if relay_peer_id is None:
            relay_peer_id = await self._select_relay(peer_info)
            if not relay_peer_id:
                raise ConnectionError("No suitable relay found")

        reservation_stream: INetStream | None = None
        relay_stream = await self.host.new_stream(relay_peer_id, [PROTOCOL_ID])
        if not relay_stream:
            raise ConnectionError(f"Could not open stream to relay {relay_peer_id}")

        try:
            # First try to make a reservation if enabled
            if self.config.enable_client:
                relay_info = self.discovery.get_relay_info(relay_peer_id)
                existing_reservation = self._reservation_streams.get(relay_peer_id)
                has_live_reservation = (
                    existing_reservation is not None
                    and relay_info is not None
                    and relay_info.has_reservation
                    and relay_info.reservation_expires_at is not None
                    and relay_info.reservation_expires_at > time.time()
                )
                success = has_live_reservation or await self._make_reservation(
                    relay_stream, relay_peer_id
                )
                if not success:
                    logger.warning(
                        "Failed to make reservation with relay %s", relay_peer_id
                    )
                    await relay_stream.close()
                    relay_stream = await self.host.new_stream(
                        relay_peer_id, [PROTOCOL_ID]
                    )
                    if not relay_stream:
                        raise ConnectionError(
                            f"Could not open circuit stream to relay {relay_peer_id}"
                        )
                else:
                    if not has_live_reservation:
                        reservation_stream = relay_stream
                        previous = self._reservation_streams.pop(relay_peer_id, None)
                        if previous is not None:
                            await previous.close()
                        self._reservation_streams[relay_peer_id] = reservation_stream
                        relay_stream = await self.host.new_stream(
                            relay_peer_id, [PROTOCOL_ID]
                        )
                        if not relay_stream:
                            raise ConnectionError(
                                "Could not open circuit stream to relay "
                                f"{relay_peer_id}"
                            )

            # Send HOP CONNECT message
            hop_msg = HopMessage(
                type=HopMessage.CONNECT,
                peer=Peer(id=peer_info.peer_id.to_bytes()),
            )
            await relay_stream.write(encode_message(hop_msg.SerializeToString()))

            # Read response
            resp_bytes = await read_message(relay_stream)
            resp = HopMessage()
            resp.ParseFromString(resp_bytes)

            if resp.type != HopMessage.STATUS or not resp.HasField("status"):
                raise ConnectionError("Relay returned an invalid connect response")

            status_code = resp.status.code
            status_msg = resp.status.message

            if status_code != StatusCode.OK:
                raise ConnectionError(f"Relay connection failed: {status_msg}")

            # Create raw connection from stream
            return RawConnection(stream=relay_stream, initiator=True)

        except Exception as e:
            await relay_stream.close()
            if reservation_stream is not None:
                self._reservation_streams.pop(relay_peer_id, None)
                await reservation_stream.close()
            raise ConnectionError(f"Failed to establish relay connection: {str(e)}")

    async def _select_relay(self, peer_info: PeerInfo) -> ID | None:
        """
        Select an appropriate relay for the given peer.

        Parameters
        ----------
        peer_info : PeerInfo
            The peer to connect to

        Returns
        -------
        Optional[ID]
            Selected relay peer ID, or None if no suitable relay found

        """
        # Prefer a relay whose reservation is already usable. This avoids
        # unnecessary reservation churn while keeping discovery fallback intact.
        now = time.time()
        relays = self.discovery.get_relays()
        active_reservations = [
            relay_id
            for relay_id in relays
            if (
                (relay_info := self.discovery.get_relay_info(relay_id)) is not None
                and relay_info.has_reservation
                and relay_info.reservation_expires_at is not None
                and relay_info.reservation_expires_at > now
            )
        ]
        if active_reservations:
            return max(
                active_reservations,
                key=lambda relay_id: self.discovery.get_relay_info(
                    relay_id
                ).reservation_expires_at
                or 0,
            )

        # Fall back to the most recently seen relay while discovery catches up.
        if relays:
            return max(
                relays,
                key=lambda relay_id: self.discovery.get_relay_info(
                    relay_id
                ).last_seen
                if self.discovery.get_relay_info(relay_id) is not None
                else 0,
            )

        # Try discovery when no relay is currently tracked.
        attempts = 0
        while attempts < self.client_config.max_auto_relay_attempts:
            relays = self.discovery.get_relays()
            if relays:
                return relays[0]

            # Wait and try discovery
            await trio.sleep(1)
            attempts += 1

        return None

    async def _make_reservation(
        self,
        stream: INetStream,
        relay_peer_id: ID,
    ) -> bool:
        """
        Make a reservation with a relay.

        Parameters
        ----------
        stream : INetStream
            Stream to the relay
        relay_peer_id : ID
            The relay's peer ID

        Returns
        -------
        bool
            True if reservation was successful

        """
        try:
            # Send reservation request
            reserve_msg = HopMessage(type=HopMessage.RESERVE)
            await stream.write(encode_message(reserve_msg.SerializeToString()))

            # Read response
            resp_bytes = await read_message(stream)
            resp = HopMessage()
            resp.ParseFromString(resp_bytes)

            if resp.type != HopMessage.STATUS or not resp.HasField("status"):
                logger.warning(
                    "Relay %s returned an invalid reservation response",
                    relay_peer_id,
                )
                return False

            status_code = resp.status.code
            status_msg = resp.status.message

            if status_code != StatusCode.OK:
                logger.warning(
                    "Reservation failed with relay %s: %s",
                    relay_peer_id,
                    status_msg,
                )
                return False

            if not resp.HasField("reservation"):
                logger.warning(
                    "Relay %s returned OK without reservation details",
                    relay_peer_id,
                )
                return False

            reservation = resp.reservation
            if not reservation.HasField("expire") or reservation.expire <= 0:
                logger.warning(
                    "Relay %s returned an invalid reservation expiry",
                    relay_peer_id,
                )
                return False

            relay_info = self.discovery.get_relay_info(relay_peer_id)
            if relay_info is not None:
                relay_info.has_reservation = True
                relay_info.reservation_expires_at = reservation.expire
                relay_info.reservation_data_limit = (
                    resp.limit.data if resp.HasField("limit") else None
                )
                relay_info.reservation_voucher = reservation.voucher or None
                relay_info.reservation_addrs = tuple(
                    multiaddr.Multiaddr(raw_addr)
                    for raw_addr in reservation.addrs
                    if _valid_multiaddr(raw_addr)
                )

            return True

        except Exception as e:
            logger.error("Error making reservation: %s", str(e))
            return False
    def create_listener(
        self,
        handler_function: Callable[[ReadWriteCloser], Awaitable[None]],
    ) -> IListener:
        """
        Create a listener for incoming relay connections.

        Parameters
        ----------
        handler_function : Callable[[ReadWriteCloser], Awaitable[None]]
            The handler function for new connections

        Returns
        -------
        IListener
            The created listener

        """
        return CircuitV2Listener(self.host, self.protocol, self.config)


class CircuitV2Listener(Service, IListener):
    """Listener for incoming relay connections."""

    def __init__(
        self,
        host: IHost,
        protocol: CircuitV2Protocol,
        config: RelayConfig,
    ) -> None:
        """
        Initialize the Circuit v2 listener.

        Parameters
        ----------
        host : IHost
            The libp2p host this listener is running on
        protocol : CircuitV2Protocol
            The Circuit v2 protocol instance
        config : RelayConfig
            Relay configuration

        """
        super().__init__()
        self.host = host
        self.protocol = protocol
        self.config = config
        self.multiaddrs: list[
            multiaddr.Multiaddr
        ] = []  # Store multiaddrs as Multiaddr objects

    async def handle_incoming_connection(
        self,
        stream: INetStream,
        remote_peer_id: ID,
    ) -> RawConnection:
        """
        Handle an incoming relay connection.

        Parameters
        ----------
        stream : INetStream
            The incoming stream
        remote_peer_id : ID
            The remote peer's ID

        Returns
        -------
        RawConnection
            The established connection

        Raises
        ------
        ConnectionError
            If the connection cannot be established

        """
        if not self.config.enable_stop:
            raise ConnectionError("Stop role is not enabled")

        try:
            # Read STOP message
            msg_bytes = await read_message(stream)
            stop_msg = StopMessage()
            stop_msg.ParseFromString(msg_bytes)

            if stop_msg.type != StopMessage.CONNECT:
                raise ConnectionError("Invalid STOP message type")

            # Create raw connection
            return RawConnection(stream=stream, initiator=False)

        except Exception as e:
            await stream.close()
            raise ConnectionError(f"Failed to handle incoming connection: {str(e)}")

    async def run(self) -> None:
        """Run the listener service."""
        # Implementation would go here

    async def listen(self, maddr: multiaddr.Multiaddr, nursery: trio.Nursery) -> bool:
        """
        Start listening on the given multiaddr.

        Parameters
        ----------
        maddr : multiaddr.Multiaddr
            The multiaddr to listen on
        nursery : trio.Nursery
            The nursery to run tasks in

        Returns
        -------
        bool
            True if listening successfully started

        """
        # Convert string to Multiaddr if needed
        addr = (
            maddr
            if isinstance(maddr, multiaddr.Multiaddr)
            else multiaddr.Multiaddr(maddr)
        )
        self.multiaddrs.append(addr)
        return True

    def get_addrs(self) -> tuple[multiaddr.Multiaddr, ...]:
        """
        Get the listening addresses.

        Returns
        -------
        tuple[multiaddr.Multiaddr, ...]
            Tuple of listening multiaddresses

        """
        return tuple(self.multiaddrs)

    async def close(self) -> None:
        """Close the listener."""
        self.multiaddrs.clear()
        await self.manager.stop()
