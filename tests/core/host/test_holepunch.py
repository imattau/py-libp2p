from collections.abc import Iterable

import pytest
from multiaddr import Multiaddr

from libp2p.host.holepunch.holepunch import (
    HOLEPUNCH_PROTOCOL_ID,
    HolePunchProtocolError,
    HolePunchService,
)
from libp2p.host.holepunch.pb.holepunch_pb2 import HolePunch
from libp2p.utils.varint import encode_varint_prefixed

ADDR = Multiaddr("/ip4/198.51.100.10/tcp/4001")


class MemoryStream:
    def __init__(self, incoming: bytes = b"", peer_id: bytes = b"peer") -> None:
        self.incoming = bytearray(incoming)
        self.writes: list[bytes] = []
        self.closed = False
        self.muxed_conn = type("MuxedConn", (), {"peer_id": peer_id})()

    async def read(self, n: int | None = None) -> bytes:
        if not self.incoming:
            return b""
        count = len(self.incoming) if n is None else n
        result = bytes(self.incoming[:count])
        del self.incoming[:count]
        return result

    async def write(self, data: bytes) -> None:
        self.writes.append(data)

    async def close(self) -> None:
        self.closed = True


class FakeHost:
    def __init__(self, stream: MemoryStream, network=None) -> None:
        self.stream = stream
        self.network = network

    def set_stream_handler(self, protocol_id, handler) -> None:
        assert protocol_id == HOLEPUNCH_PROTOCOL_ID
        self.handler = handler

    def get_addrs(self) -> Iterable[Multiaddr]:
        return (ADDR,)

    def get_network(self):
        return self.network

    async def new_stream(self, peer_id, protocols):
        assert protocols == [HOLEPUNCH_PROTOCOL_ID]
        return self.stream


@pytest.mark.trio
async def test_connect_exchanges_candidates_and_syncs() -> None:
    response = HolePunch(type=HolePunch.CONNECT, ObsAddrs=[ADDR.to_bytes()])
    stream = MemoryStream(encode_varint_prefixed(response.SerializeToString()))
    service = HolePunchService(FakeHost(stream))

    assert await service.connect(b"peer") == (ADDR,)
    assert stream.closed
    assert len(stream.writes) == 2

    connect = HolePunch()
    connect.ParseFromString(stream.writes[0][1:])
    assert connect.type == HolePunch.CONNECT
    assert list(connect.ObsAddrs) == [ADDR.to_bytes()]
    assert stream.writes[1] == encode_varint_prefixed(
        HolePunch(type=HolePunch.SYNC).SerializeToString()
    )


@pytest.mark.trio
async def test_connect_retries_after_direct_dial_failure() -> None:
    response = HolePunch(type=HolePunch.CONNECT, ObsAddrs=[ADDR.to_bytes()])
    streams = [
        MemoryStream(encode_varint_prefixed(response.SerializeToString()))
        for _ in range(2)
    ]

    class RetryHost(FakeHost):
        def __init__(self) -> None:
            super().__init__(streams[0], RetryNetwork())
            self.streams = streams

        async def new_stream(self, peer_id, protocols):
            return self.streams.pop(0)

    class RetryNetwork:
        def __init__(self) -> None:
            self.attempts = 0

        async def dial_peer_direct(self, peer_id, addresses) -> None:
            self.attempts += 1
            if self.attempts == 1:
                raise RuntimeError("direct dial failed")

    host = RetryHost()
    service = HolePunchService(host)

    assert await service.connect(b"peer") == (ADDR,)
    assert host.network.attempts == 2


@pytest.mark.trio
async def test_handler_rejects_sync_as_first_message() -> None:
    sync = HolePunch(type=HolePunch.SYNC)
    stream = MemoryStream(encode_varint_prefixed(sync.SerializeToString()))
    service = HolePunchService(FakeHost(stream))

    await service.handle_stream(stream)

    assert stream.closed
    assert stream.writes == []


@pytest.mark.trio
async def test_handler_dials_remote_candidates_after_sync() -> None:
    connect = HolePunch(type=HolePunch.CONNECT, ObsAddrs=[ADDR.to_bytes()])
    sync = HolePunch(type=HolePunch.SYNC)
    stream = MemoryStream(
        encode_varint_prefixed(connect.SerializeToString())
        + encode_varint_prefixed(sync.SerializeToString())
    )

    class Network:
        def __init__(self) -> None:
            self.calls = []

        async def dial_peer_direct(self, peer_id, addresses) -> None:
            self.calls.append((peer_id, addresses))

    network = Network()
    service = HolePunchService(FakeHost(stream, network))

    await service.handle_stream(stream)

    assert network.calls == [(b"peer", (ADDR,))]
    assert stream.closed


def test_message_size_is_bounded() -> None:
    with pytest.raises(HolePunchProtocolError):
        HolePunchService._message(HolePunch.CONNECT, [ADDR] * 1000)
