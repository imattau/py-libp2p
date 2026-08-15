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

    def __init__(self, key_pair: KeyPair, nursery: trio.Nursery | None = None) -> None:
        self.key_pair = key_pair
        self.nursery = nursery

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

    def create_listener(self, handler_function: THandler) -> IListener:
        return QuicListener(handler_function, self.key_pair)


def _is_quic_v1(maddr: Multiaddr) -> bool:
    protocols = maddr.protocols()
    return bool(protocols) and protocols[-1].name == QUIC_V1_MULTIADDR_PROTOCOL
