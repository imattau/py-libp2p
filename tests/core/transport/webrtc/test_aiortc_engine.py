import importlib.util

import pytest
import trio

from libp2p.transport.webrtc.aiortc_engine import (
    AiortcWebRTCEngine,
    WebRTCDependencyError,
    _candidate_from_data,
)
from libp2p.transport.webrtc.connection import WebRTCConnection


def test_register_data_channel_handler_uses_aiortc_event_name() -> None:
    from libp2p.transport.webrtc.aiortc_engine import _register_data_channel_handler

    class PeerConnection:
        def __init__(self) -> None:
            self.events: list[tuple[str, object]] = []

        def on(self, event: str, handler: object) -> None:
            self.events.append((event, handler))

    peer_connection = PeerConnection()
    handler = object()

    _register_data_channel_handler(peer_connection, handler)

    assert peer_connection.events == [("datachannel", handler)]


@pytest.mark.trio
async def test_engine_reports_missing_optional_dependency() -> None:
    if importlib.util.find_spec("aiortc") is not None:
        pytest.skip("aiortc is installed; integration coverage applies")

    engine = AiortcWebRTCEngine()
    with pytest.raises(WebRTCDependencyError, match="aiortc"):
        await engine.start()


def test_candidate_from_data_maps_browser_candidate_fields() -> None:
    class Candidate:
        def __init__(self, **kwargs: object) -> None:
            self.values = kwargs

    candidate = _candidate_from_data(
        {
            "candidate": "candidate:1 1 UDP 123 192.0.2.1 5000 typ host "
            "raddr 192.0.2.2 rport 5001",
            "sdpMid": "0",
            "sdpMLineIndex": 0,
            "usernameFragment": "ufrag",
        },
        Candidate,
    )

    assert candidate.values == {
        "foundation": "1",
        "component": 1,
        "protocol": "udp",
        "priority": 123,
        "ip": "192.0.2.1",
        "port": 5000,
        "type": "host",
        "sdpMid": "0",
        "sdpMLineIndex": 0,
        "usernameFragment": "ufrag",
        "relatedAddress": "192.0.2.2",
        "relatedPort": 5001,
        "tcpType": None,
    }


@pytest.mark.trio
async def test_aiortc_engine_exchanges_framed_data_channel_messages() -> None:
    if importlib.util.find_spec("aiortc") is None:
        pytest.skip("aiortc is not installed")

    first = AiortcWebRTCEngine()
    second = AiortcWebRTCEngine()
    try:
        await first.start()
        await second.start()
        outbound = await first.create_data_channel(True)
        offer = await first.create_offer()
        received = trio.Event()
        holder: dict[str, WebRTCConnection] = {}

        async def accept() -> None:
            holder["connection"] = await second.accept_data_channel()
            received.set()

        async with trio.open_nursery() as nursery:
            nursery.start_soon(accept)
            await trio.sleep(0.1)
            await second.set_remote_description(offer)
            answer = await second.create_answer()
            await first.set_remote_description(answer)
            with trio.fail_after(10):
                await received.wait()
            inbound = holder["connection"]
            await outbound.wait_ready()
            await inbound.wait_ready()
            await outbound.write(b"hello over aiortc")
            with trio.fail_after(10):
                assert await inbound.read() == b"hello over aiortc"
            nursery.cancel_scope.cancel()
    finally:
        await first.close()
        await second.close()


@pytest.mark.trio
async def test_aiortc_engine_exchanges_negotiated_direct_channel() -> None:
    if importlib.util.find_spec("aiortc") is None:
        pytest.skip("aiortc is not installed")

    first = AiortcWebRTCEngine()
    second = AiortcWebRTCEngine()
    try:
        await first.start()
        await second.start()
        outbound = await first.create_direct_data_channel(True)
        inbound = await second.create_direct_data_channel(False)
        offer = await first.create_offer()
        await second.set_remote_description(offer)
        answer = await second.create_answer()
        await first.set_remote_description(answer)
        await outbound.wait_ready()
        await inbound.wait_ready()
        await outbound.write(b"direct channel")
        with trio.fail_after(10):
            assert await inbound.read() == b"direct channel"
    finally:
        await first.close()
        await second.close()
