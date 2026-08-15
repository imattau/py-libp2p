import json

import pytest
from multiaddr import Multiaddr

from libp2p.peer.id import ID
from libp2p.peer.peerinfo import PeerInfo
from libp2p.routing.delegated import DelegatedContentRouting

PEER_ID = "12D3KooWJ5w2Qh7aG2sRrL4n9LhKzV5d3f1Wq9pT8xY6uN4mC7bA"


@pytest.mark.trio
async def test_find_provider_parses_json_envelope_and_limits_results() -> None:
    requests: list[tuple[str, dict[str, str]]] = []

    async def fetch(url: str, headers: dict[str, str]) -> bytes:
        requests.append((url, headers))
        return json.dumps(
            {
                "Providers": [
                    {
                        "Schema": "peer",
                        "ID": PEER_ID,
                        "Addrs": ["/ip4/127.0.0.1/tcp/4001"],
                    },
                    {"Schema": "peer", "ID": PEER_ID, "Addrs": []},
                ]
            }
        ).encode()

    routing = DelegatedContentRouting("https://routing.example/routing/v1", fetch=fetch)
    providers = [
        provider async for provider in routing.find_provider_iter(b"bafytest", 1)
    ]

    assert providers == [
        PeerInfo(ID.from_base58(PEER_ID), [Multiaddr("/ip4/127.0.0.1/tcp/4001")])
    ]
    assert requests == [
        (
            "https://routing.example/routing/v1/providers/bafytest",
            {"Accept": "application/x-ndjson, application/json"},
        )
    ]


@pytest.mark.trio
async def test_find_provider_parses_ndjson_and_skips_invalid_records() -> None:
    async def fetch(url: str, headers: dict[str, str]) -> bytes:
        return (
            b'{"Addrs": ["/ip4/127.0.0.1/tcp/4001"]}\n'
            + json.dumps({"ID": PEER_ID, "Addrs": ["/ip4/127.0.0.1/tcp/4002"]}).encode()
        )

    routing = DelegatedContentRouting("https://routing.example", fetch=fetch)
    providers = [
        provider async for provider in routing.find_provider_iter(b"bafytest", 20)
    ]

    assert len(providers) == 1
    assert str(providers[0].addrs[0]) == "/ip4/127.0.0.1/tcp/4002"


@pytest.mark.trio
async def test_find_provider_rejects_binary_cid() -> None:
    routing = DelegatedContentRouting("https://routing.example", fetch=lambda *_: None)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="string-encoded CID"):
        _ = [provider async for provider in routing.find_provider_iter(b"\xff", 1)]


@pytest.mark.trio
async def test_provide_is_not_supported() -> None:
    routing = DelegatedContentRouting("https://routing.example", fetch=lambda *_: None)  # type: ignore[arg-type]
    with pytest.raises(NotImplementedError):
        await routing.provide(b"bafytest")
