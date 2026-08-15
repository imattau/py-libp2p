import pytest

from libp2p.discovery.random_walk import RandomWalkDiscovery


class PeerStore:
    def __init__(self, addresses):
        self.addresses = addresses

    def addrs(self, peer_id):
        return self.addresses.get(peer_id, ())


class Host:
    def __init__(self, peer_id, addresses):
        self.peer_id = peer_id
        self.peerstore = PeerStore(addresses)

    def get_id(self):
        return self.peer_id

    def get_peerstore(self):
        return self.peerstore


class Routing:
    async def find_closest_peers_network(self, target, count):
        assert len(target) == 32
        assert count == 2
        return [b"self", b"peer", b"missing"]


class DHT:
    peer_routing = Routing()


@pytest.mark.trio
async def test_random_walk_publishes_only_addressable_new_peers():
    service = RandomWalkDiscovery(
        Host(b"self", {b"peer": ("/ip4/127.0.0.1/tcp/4001",)}),
        DHT(),
        result_count=2,
    )

    discovered = await service.discover_once()

    assert [info.peer_id for info in discovered] == [b"peer"]
    assert service.discovered_peers == {b"peer"}
    assert await service.discover_once() == ()


def test_random_walk_validates_configuration():
    host = Host(b"self", {})
    with pytest.raises(ValueError):
        RandomWalkDiscovery(host, DHT(), interval=0)
    with pytest.raises(ValueError):
        RandomWalkDiscovery(host, DHT(), result_count=0)
