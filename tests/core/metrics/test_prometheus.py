from types import SimpleNamespace

import pytest

from libp2p.metrics.prometheus import PrometheusMetrics


def test_render_includes_swarm_and_resource_metrics() -> None:
    swarm = SimpleNamespace(connections={1: object()}, listeners={"tcp": object()})
    resource_manager = SimpleNamespace(
        system=SimpleNamespace(
            stat=lambda: SimpleNamespace(
                num_conns=2,
                num_streams=3,
                num_fd=4,
                memory=5,
            )
        )
    )
    metrics = PrometheusMetrics(swarm, resource_manager)

    body = metrics.render().decode()

    assert "libp2p_swarm_connections 1" in body
    assert "libp2p_swarm_listeners 1" in body
    assert "libp2p_resource_connections 2" in body
    assert "libp2p_resource_streams 3" in body
    assert "libp2p_resource_fds 4" in body
    assert "libp2p_resource_memory_bytes 5" in body


def test_custom_collectors_are_sorted_and_validated() -> None:
    metrics = PrometheusMetrics()
    metrics.register("libp2p_protocol", lambda: {"messages": 4, "errors": 1})

    assert metrics.render().decode().splitlines() == [
        "libp2p_protocol_errors 1",
        "libp2p_protocol_messages 4",
    ]


def test_duplicate_or_invalid_collectors_are_rejected() -> None:
    metrics = PrometheusMetrics()
    metrics.register("libp2p_protocol", lambda: {})
    with pytest.raises(ValueError, match="already registered"):
        metrics.register("libp2p_protocol", lambda: {})
    with pytest.raises(ValueError, match="invalid"):
        metrics.register("bad-name", lambda: {})


@pytest.mark.trio
async def test_metrics_endpoint_returns_prometheus_response() -> None:
    class FakeStream:
        response = b""

        async def receive_some(self, size: int) -> bytes:
            return b"GET /metrics HTTP/1.1\r\nHost: localhost\r\n\r\n"

        async def send_all(self, data: bytes) -> None:
            self.response = data

        async def aclose(self) -> None:
            return None

    stream = FakeStream()
    await PrometheusMetrics()._handle_connection(stream)

    assert stream.response.startswith(b"HTTP/1.1 200 OK\r\n")
    assert b"Content-Type: text/plain; version=0.0.4" in stream.response
