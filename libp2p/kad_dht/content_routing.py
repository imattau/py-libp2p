"""Content-routing adapter backed by the native Kademlia DHT."""

from collections.abc import AsyncIterator
from typing import TYPE_CHECKING

from libp2p.abc import IContentRouting
from libp2p.peer.peerinfo import PeerInfo

if TYPE_CHECKING:
    from .kad_dht import KadDHT


class KadContentRouting(IContentRouting):
    """Expose provider advertisement and lookup through one DHT-facing API."""

    def __init__(self, dht: "KadDHT") -> None:
        self.dht = dht

    async def provide(self, cid: bytes, announce: bool = True) -> bool:
        if not announce:
            self.dht.provider_store.add_provider(
                cid,
                PeerInfo(self.dht.local_peer_id, self.dht.host.get_addrs()),
            )
            return True
        return await self.dht.provide(cid)

    async def find_provider_iter(
        self, cid: bytes, count: int = 20
    ) -> AsyncIterator[PeerInfo]:
        for provider in await self.dht.find_providers(cid, count):
            yield provider
