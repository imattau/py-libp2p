import importlib.util

import pytest

from libp2p.transport.webrtc.aiortc_engine import (
    AiortcWebRTCEngine,
    WebRTCDependencyError,
)


@pytest.mark.trio
async def test_engine_reports_missing_optional_dependency() -> None:
    if importlib.util.find_spec("aiortc") is not None:
        pytest.skip("aiortc is installed; integration coverage applies")

    engine = AiortcWebRTCEngine()
    with pytest.raises(WebRTCDependencyError, match="aiortc"):
        await engine.start()
