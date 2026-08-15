from OpenSSL import SSL

from libp2p.abc import IRawConnection
from libp2p.crypto.keys import PublicKey
from libp2p.peer.id import ID
from libp2p.security.base_session import BaseSession
from libp2p.security.exceptions import HandshakeFailure

from .certificate import (
    peer_id_from_certificate,
    public_key_from_certificate,
)
from .context import create_tls_context
from .identity import TLSIdentity


class TLSConnection:
    """Drive a PyOpenSSL memory-BIO connection over an async raw stream."""

    def __init__(
        self,
        raw_conn: IRawConnection,
        identity: TLSIdentity,
        *,
        is_server: bool,
    ) -> None:
        self.raw_conn = raw_conn
        self.identity = identity
        self.is_server = is_server
        self._tls = SSL.Connection(
            create_tls_context(identity, is_server=is_server),
            None,
        )
        if is_server:
            self._tls.set_accept_state()
        else:
            self._tls.set_connect_state()
            self._tls.set_tlsext_host_name(b"libp2p")
        self._handshaken = False

    async def handshake(self) -> tuple[ID, PublicKey]:
        try:
            while True:
                try:
                    self._tls.do_handshake()
                    break
                except SSL.WantReadError:
                    await self._flush()
                    if not await self._read():
                        raise HandshakeFailure("TLS connection closed")
                except SSL.WantWriteError:
                    await self._flush()
            await self._flush()
            certificate = self._tls.get_peer_certificate(as_cryptography=True)
            if certificate is None:
                raise HandshakeFailure("TLS peer certificate is missing")
            peer_id = peer_id_from_certificate(certificate)
            public_key = public_key_from_certificate(certificate)
            self._handshaken = True
            return peer_id, public_key
        except HandshakeFailure:
            raise
        except Exception as error:
            raise HandshakeFailure("TLS handshake failed") from error

    async def read(self, n: int | None = None) -> bytes:
        if not self._handshaken:
            raise RuntimeError("TLS handshake has not completed")
        size = n or 16384
        while True:
            try:
                return self._tls.recv(size)
            except SSL.WantReadError:
                await self._flush()
                if not await self._read():
                    return b""
            except SSL.WantWriteError:
                await self._flush()
            except SSL.ZeroReturnError:
                return b""

    async def write(self, data: bytes) -> None:
        if not self._handshaken:
            raise RuntimeError("TLS handshake has not completed")
        offset = 0
        while offset < len(data):
            try:
                offset += self._tls.send(data[offset:])
            except SSL.WantReadError:
                await self._flush()
                await self._read()
            except SSL.WantWriteError:
                await self._flush()
            await self._flush()

    async def close(self) -> None:
        try:
            self._tls.shutdown()
            await self._flush()
        except Exception:
            pass
        await self.raw_conn.close()

    def get_remote_address(self) -> tuple[str, int] | None:
        return self.raw_conn.get_remote_address()

    async def _flush(self) -> None:
        while True:
            try:
                data = self._tls.bio_read(16384)
            except SSL.WantReadError:
                return
            if not data:
                return
            await self.raw_conn.write(data)

    async def _read(self) -> bool:
        data = await self.raw_conn.read(16384)
        if not data:
            return False
        self._tls.bio_write(data)
        return True


class TLSSession(BaseSession):
    """Secure-session facade over a completed TLS connection."""

    def __init__(
        self,
        connection: TLSConnection,
        remote_peer: ID,
        remote_public_key: PublicKey,
    ) -> None:
        super().__init__(
            local_peer=connection.identity.peer_id,
            local_private_key=connection.identity.key_pair.private_key,
            remote_peer=remote_peer,
            remote_permanent_pubkey=remote_public_key,
            is_initiator=not connection.is_server,
        )
        self.connection = connection

    async def read(self, n: int | None = None) -> bytes:
        return await self.connection.read(n)

    async def write(self, data: bytes) -> None:
        await self.connection.write(data)

    async def close(self) -> None:
        await self.connection.close()

    def get_remote_address(self) -> tuple[str, int] | None:
        return self.connection.get_remote_address()
