import pytest

from libp2p.transport.quic.socket import TrioQuicDatagramSocket


class FakeSocket:
    def __init__(self):
        self.sent = []
        self.closed = False

    async def recvfrom(self, max_bytes):
        return b"packet"[:max_bytes], ("127.0.0.1", 42)

    async def sendto(self, data, addr):
        self.sent.append((data, addr))

    def getsockname(self):
        return ("127.0.0.1", 1234)

    def close(self):
        self.closed = True


@pytest.mark.trio
async def test_trio_quic_datagram_socket_delegates_io():
    socket = FakeSocket()
    adapter = TrioQuicDatagramSocket(socket)

    packet, addr = await adapter.recvfrom(10)
    await adapter.sendto(packet, addr)

    assert (packet, addr) == (b"packet", ("127.0.0.1", 42))
    assert socket.sent == [(b"packet", ("127.0.0.1", 42))]
    assert adapter.getsockname() == ("127.0.0.1", 1234)
    await adapter.aclose()
    assert socket.closed
