from typing import Any

import trio

from .driver import QuicDatagramSocket


class TrioQuicDatagramSocket(QuicDatagramSocket):
    """Adapt a Trio UDP socket to the QUIC driver socket protocol."""

    def __init__(self, socket: trio.socket.SocketType) -> None:
        self.socket = socket

    @classmethod
    async def bind(
        cls,
        host: str,
        port: int,
    ) -> "TrioQuicDatagramSocket":
        socket = trio.socket.socket(trio.socket.AF_INET, trio.socket.SOCK_DGRAM)
        await socket.bind((host, port))
        return cls(socket)

    async def recvfrom(self, max_bytes: int) -> tuple[bytes, Any]:
        return await self.socket.recvfrom(max_bytes)

    async def sendto(self, data: bytes, addr: Any) -> None:
        await self.socket.sendto(data, addr)

    def getsockname(self) -> Any:
        return self.socket.getsockname()

    async def aclose(self) -> None:
        self.socket.close()
