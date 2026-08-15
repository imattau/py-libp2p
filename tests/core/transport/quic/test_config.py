import pytest

from libp2p.transport.quic import (
    QuicTransportConfig,
)


def test_quic_transport_config_defaults():
    config = QuicTransportConfig()

    assert config.idle_timeout == 30.0
    assert config.handshake_timeout == 10.0
    assert config.max_datagram_size == 1200
    assert config.max_incoming_streams == 100
    assert config.max_outgoing_streams == 100


@pytest.mark.parametrize(
    "field, value",
    (
        ("idle_timeout", 0),
        ("handshake_timeout", 0),
        ("max_datagram_size", 1199),
        ("max_incoming_streams", 0),
        ("max_outgoing_streams", 0),
    ),
)
def test_quic_transport_config_rejects_invalid_limits(field, value):
    with pytest.raises(ValueError):
        QuicTransportConfig(**{field: value})
