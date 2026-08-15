import pytest

from libp2p import get_default_muxer, set_default_muxer


@pytest.fixture
def security_protocol():
    return None


@pytest.fixture(autouse=True)
def restore_default_muxer():
    previous = get_default_muxer()
    yield
    set_default_muxer(previous)
