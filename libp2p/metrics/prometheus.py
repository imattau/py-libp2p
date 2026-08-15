"""Small Prometheus exposition endpoint for native libp2p services."""

from collections.abc import Callable, Mapping
from typing import Any

import trio

MetricValue = int | float
MetricCollector = Callable[[], Mapping[str, MetricValue]]


class PrometheusMetrics:
    """Render built-in swarm and resource-manager metrics over HTTP."""

    def __init__(self, swarm: Any | None = None, resource_manager: Any | None = None):
        self.swarm = swarm
        self.resource_manager = resource_manager
        self._collectors: dict[str, MetricCollector] = {}

    def register(self, prefix: str, collector: MetricCollector) -> None:
        """Register a collector whose keys become metric suffixes."""
        _validate_metric_name(prefix)
        if prefix in self._collectors:
            raise ValueError(f"metric collector already registered: {prefix}")
        self._collectors[prefix] = collector

    def render(self) -> bytes:
        """Return the current metrics in Prometheus text format."""
        samples: dict[str, MetricValue] = {}
        if self.swarm is not None:
            samples.update(
                {
                    "libp2p_swarm_connections": len(self.swarm.connections),
                    "libp2p_swarm_listeners": len(self.swarm.listeners),
                }
            )
        if self.resource_manager is not None:
            system = getattr(self.resource_manager, "system", None)
            stat = system.stat() if system is not None else None
            if stat is not None:
                samples.update(
                    {
                        "libp2p_resource_connections": stat.num_conns,
                        "libp2p_resource_streams": stat.num_streams,
                        "libp2p_resource_fds": stat.num_fd,
                        "libp2p_resource_memory_bytes": stat.memory,
                    }
                )
        for prefix, collector in self._collectors.items():
            for suffix, value in collector().items():
                _validate_metric_name(suffix)
                samples[f"{prefix}_{suffix}"] = value

        lines = [
            f"{name} {value}"
            for name, value in sorted(samples.items())
        ]
        return ("\n".join(lines) + "\n").encode("utf-8") if lines else b""

    async def serve(self, port: int, host: str = "127.0.0.1") -> None:
        """Serve ``GET /metrics`` until the surrounding nursery is cancelled."""
        await trio.serve_tcp(self._handle_connection, port, host=host)

    async def _handle_connection(self, stream: Any) -> None:
        request = await stream.receive_some(4096)
        request_line = request.split(b"\r\n", 1)[0].split(b" ", 2)
        if (
            len(request_line) >= 2
            and request_line[0] == b"GET"
            and request_line[1] == b"/metrics"
        ):
            body = self.render()
            response = (
                b"HTTP/1.1 200 OK\r\n"
                b"Content-Type: text/plain; version=0.0.4; charset=utf-8\r\n"
                + f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n".encode()
                + body
            )
        else:
            body = b"not found\n"
            response = (
                b"HTTP/1.1 404 Not Found\r\n"
                + f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n".encode()
                + body
            )
        await stream.send_all(response)
        await stream.aclose()


def _validate_metric_name(name: str) -> None:
    if not name or not name.replace("_", "a").isalnum() or name[0].isdigit():
        raise ValueError(f"invalid Prometheus metric name: {name!r}")
