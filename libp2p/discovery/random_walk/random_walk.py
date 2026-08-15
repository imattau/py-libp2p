"""Kademlia-backed random-walk peer discovery."""

from collections.abc import Iterable
import logging
import secrets
from typing import Any

import trio

from libp2p.discovery.events.peerDiscovery import peerDiscovery
from libp2p.peer.peerinfo import PeerInfo

logger = logging.getLogger("libp2p.discovery.random_walk")


class RandomWalkDiscovery:
    """Periodically query random DHT keys and publish newly found peers."""

    def __init__(
        self,
        host: Any,
        dht: Any,
        interval: float = 60.0,
        result_count: int = 20,
    ) -> None:
        if interval <= 0:
            raise ValueError("interval must be positive")
        if result_count <= 0:
            raise ValueError("result_count must be positive")
        self.host = host
        self.dht = dht
        self.interval = interval
        self.result_count = result_count
        self.discovered_peers: set[Any] = set()

    async def discover_once(self) -> tuple[PeerInfo, ...]:
        """Perform one random DHT lookup and publish addressable peers."""
        peer_ids: Iterable[Any] = (
            await self.dht.peer_routing.find_closest_peers_network(
                secrets.token_bytes(32), self.result_count
            )
        )
        discovered: list[PeerInfo] = []
        for peer_id in peer_ids:
            if peer_id == self.host.get_id() or peer_id in self.discovered_peers:
                continue
            try:
                addresses = tuple(self.host.get_peerstore().addrs(peer_id))
            except Exception as error:
                logger.debug(
                    "unable to read addresses for discovered peer %s: %s",
                    peer_id,
                    error,
                )
                continue
            if not addresses:
                continue
            peer_info = PeerInfo(peer_id, addresses)
            self.discovered_peers.add(peer_id)
            discovered.append(peer_info)
            peerDiscovery.emit_peer_discovered(peer_info)
        return tuple(discovered)

    async def run(self) -> None:
        """Run random walks until the surrounding Trio scope is cancelled."""
        while True:
            try:
                await self.discover_once()
            except Exception as error:
                logger.debug("random walk failed: %s", error, exc_info=error)
            await trio.sleep(self.interval)

    def stop(self) -> None:
        """Clear local discovery state before restarting the service."""
        self.discovered_peers.clear()
