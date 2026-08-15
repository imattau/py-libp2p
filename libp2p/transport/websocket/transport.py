from __future__ import annotations

import logging
import ssl

from multiaddr import Multiaddr
import trio
from trio_typing import TaskStatus
from trio_websocket import WebSocketRequest, open_websocket_url, serve_websocket

from libp2p.abc import IListener, IRawConnection, ITransport
from libp2p.custom_types import THandler
from libp2p.transport.exceptions import OpenConnectionError

from .connection import WebSocketConnection

logger = logging.getLogger("libp2p.transport.websocket")


def _websocket_params(maddr: Multiaddr) -> tuple[str, int, bool]:
    host = maddr.value_for_protocol("ip4") or maddr.value_for_protocol("dns4")
    port = maddr.value_for_protocol("tcp")
    if host is None or port is None:
        raise OpenConnectionError(
            f"WebSocket address requires host and TCP port: {maddr}"
        )
    try:
        port_number = int(port)
    except ValueError as error:
        raise OpenConnectionError(f"Invalid WebSocket TCP port: {port}") from error
    protocol_names = {protocol.name for protocol in maddr.protocols()}
    if "wss" in protocol_names:
        return host, port_number, True
    if "ws" in protocol_names:
        return host, port_number, False
    raise OpenConnectionError(f"WebSocket address requires /ws or /wss: {maddr}")


class WebSocketListener(IListener):
    def __init__(self, handler_function: THandler) -> None:
        self.handler = handler_function
        self._server = None
        self._host = ""
        self._port = 0
        self._ssl_context: ssl.SSLContext | None = None

    async def listen(self, maddr: Multiaddr, nursery: trio.Nursery) -> bool:
        host, port, secure = _websocket_params(maddr)
        self._host, self._port = host, port
        self._ssl_context = _server_ssl_context(maddr) if secure else None

        async def handler(request: WebSocketRequest) -> None:
            websocket = await request.accept()
            await self.handler(WebSocketConnection(websocket, False))

        async def serve(
            task_status: TaskStatus[object] = trio.TASK_STATUS_IGNORED,
        ) -> None:
            await serve_websocket(
                handler,
                host,
                port,
                self._ssl_context,
                task_status=task_status,
            )

        self._server = await nursery.start(serve)
        self._port = self._server.port
        return self._server is not None

    def get_addrs(self) -> tuple[Multiaddr, ...]:
        if self._server is None:
            return ()
        scheme = "wss" if self._ssl_context is not None else "ws"
        return (Multiaddr(f"/ip4/{self._host}/tcp/{self._port}/{scheme}"),)

    async def close(self) -> None:
        if self._server is not None:
            for listener in self._server._listeners:
                await listener.aclose()
            self._server = None


class WebSocket(ITransport):
    async def dial(self, maddr: Multiaddr) -> IRawConnection:
        host, port, secure = _websocket_params(maddr)
        scheme = "wss" if secure else "ws"
        ssl_context = _client_ssl_context(maddr) if secure else None
        try:
            context_manager = open_websocket_url(
                f"{scheme}://{host}:{port}/",
                ssl_context=ssl_context,
            )
            websocket = await context_manager.__aenter__()
        except Exception as error:
            raise OpenConnectionError(
                f"Failed to open WebSocket to {maddr}: {error}"
            ) from error
        return WebSocketConnection(websocket, True, context_manager)

    def create_listener(self, handler_function: THandler) -> WebSocketListener:
        return WebSocketListener(handler_function)


def _server_ssl_context(maddr: Multiaddr) -> ssl.SSLContext:
    raise OpenConnectionError(
        f"TLS configuration is required for wss listener: {maddr}"
    )


def _client_ssl_context(maddr: Multiaddr) -> ssl.SSLContext:
    raise OpenConnectionError(f"TLS configuration is required for wss dial: {maddr}")
