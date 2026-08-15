from aioquic.quic.connection import QuicConnection

from libp2p.transport.quic.config import QuicTransportConfig
from libp2p.transport.quic.connection import create_quic_connection


def test_create_quic_connection_configures_aioquic():
    connection = create_quic_connection(
        is_client=True,
        config=QuicTransportConfig(idle_timeout=7.5, max_datagram_size=1400),
    )

    assert isinstance(connection, QuicConnection)
    assert connection.configuration.is_client
    assert connection.configuration.alpn_protocols == ["libp2p"]
    assert connection.configuration.idle_timeout == 7.5
    assert connection.configuration.max_datagram_size == 1400
