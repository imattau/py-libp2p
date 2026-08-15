from multiaddr import Multiaddr
import trio

from libp2p.abc import (
    IListener,
    IRawConnection,
    ITransport,
)
from libp2p.crypto.keys import KeyPair
from libp2p.custom_types import THandler

from .config import QUIC_V1_MULTIADDR_PROTOCOL
from .dialer import QuicDialer
from .listener import QuicListener


class QuicTransport(ITransport):
    """Public transport facade for the native Trio QUIC implementation."""

    native_connections = True
    supports_hole_punching = True

    def __init__(self, key_pair: KeyPair, nursery: trio.Nursery | None = None) -> None:
        self.key_pair = key_pair
        self.nursery = nursery
        self._listeners: list[QuicListener] = []

    async def dial(self, maddr: Multiaddr) -> IRawConnection:
        if self.nursery is None:
            raise RuntimeError("QuicTransport.dial requires a Trio nursery")
        if not _is_quic_v1(maddr):
            raise ValueError(f"not a QUIC v1 multiaddr: {maddr}")
        return await QuicDialer().dial_multiaddr(
            maddr,
            self.key_pair,
            self.nursery,
        )

    async def dial_hole_punch(
        self, maddr: Multiaddr, local_maddr: Multiaddr
    ) -> IRawConnection:
        if self.nursery is None:
            raise RuntimeError("QuicTransport.dial requires a Trio nursery")
        if not _is_quic_v1(maddr):
            raise ValueError(f"not a QUIC v1 multiaddr: {maddr}")
        local_host = local_maddr.value_for_protocol("ip4")
        local_port = local_maddr.value_for_protocol("udp")
        if local_host is None or local_port is None:
            raise ValueError(f"invalid local QUIC multiaddr: {local_maddr}")
        for listener in self._listeners:
            if local_maddr in listener.get_addrs():
                return await listener.dial_hole_punch(
                    maddr,
                    self.key_pair,
                    self.nursery,
                )
        return await QuicDialer().dial_hole_punch(
            maddr,
            self.key_pair,
            self.nursery,
            (local_host, int(local_port)),
            expected_peer_id=None,
        )

    def create_listener(self, handler_function: THandler) -> IListener:
        listener = QuicListener(handler_function, self.key_pair)
        self._listeners.append(listener)
        return listener


def _is_quic_v1(maddr: Multiaddr) -> bool:
    protocols = maddr.protocols()
    return any(protocol.name == QUIC_V1_MULTIADDR_PROTOCOL for protocol in protocols)
