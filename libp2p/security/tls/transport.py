from libp2p.abc import IRawConnection, ISecureConn, ISecureTransport
from libp2p.peer.id import ID

from .connection import TLSConnection, TLSSession
from .identity import TLSIdentity


class TLSTransport(ISecureTransport):
    """libp2p TLS 1.3 secure transport."""

    def __init__(self, key_pair) -> None:
        self.identity = TLSIdentity.create(key_pair)

    async def secure_inbound(self, conn: IRawConnection) -> ISecureConn:
        connection = TLSConnection(conn, self.identity, is_server=True)
        peer_id, public_key = await connection.handshake()
        return TLSSession(connection, peer_id, public_key)

    async def secure_outbound(
        self, conn: IRawConnection, peer_id: ID
    ) -> ISecureConn:
        connection = TLSConnection(conn, self.identity, is_server=False)
        received_peer_id, public_key = await connection.handshake()
        if received_peer_id != peer_id:
            await connection.close()
            raise ValueError("TLS peer identity does not match expected peer")
        return TLSSession(connection, received_peer_id, public_key)
