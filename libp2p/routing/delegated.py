"""Client for the Delegated Routing V1 HTTP API."""

import base64
import binascii
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
import json
from typing import Any
import urllib.error
import urllib.parse
import urllib.request

from multiaddr import Multiaddr
import trio

from libp2p.abc import IContentRouting
from libp2p.peer.id import ID
from libp2p.peer.peerinfo import PeerInfo

Fetch = Callable[[str, Mapping[str, str]], Awaitable[bytes]]


class DelegatedContentRouting(IContentRouting):
    """
    Find providers through a Delegated Routing V1 HTTP endpoint.

    The delegated API is read-only: provider advertisements remain the
    responsibility of a native content router such as the Kademlia adapter.
    ``fetch`` is injectable to make protocol parsing deterministic in tests.
    """

    def __init__(
        self,
        endpoint: str,
        *,
        timeout: float = 10.0,
        fetch: Fetch | None = None,
    ) -> None:
        self.endpoint = endpoint.rstrip("/")
        if self.endpoint.endswith("/routing/v1"):
            self.endpoint = self.endpoint[: -len("/routing/v1")]
        self.timeout = timeout
        self._fetch = fetch or self._fetch_http

    async def provide(self, cid: bytes | str, announce: bool = True) -> None:
        raise NotImplementedError("delegated routing does not advertise providers")

    async def find_provider_iter(
        self, cid: bytes | str, count: int = 20
    ) -> AsyncIterator[PeerInfo]:
        if count <= 0:
            return

        cid_text = _cid_text(cid)
        path = "/routing/v1/providers/" + urllib.parse.quote(cid_text, safe="")
        payload = await self._fetch(
            self.endpoint + path,
            {"Accept": "application/x-ndjson, application/json"},
        )

        yielded = 0
        for record in _provider_records(payload):
            try:
                provider = _peer_info(record)
            except (KeyError, TypeError, ValueError, binascii.Error):
                continue
            yield provider
            yielded += 1
            if yielded >= count:
                return

    async def _fetch_http(self, url: str, headers: Mapping[str, str]) -> bytes:
        def request() -> bytes:
            req = urllib.request.Request(url, headers=dict(headers), method="GET")
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as response:
                    return response.read()
            except urllib.error.HTTPError as error:
                if error.code == 404:
                    return b'{"Providers": []}'
                raise

        return await trio.to_thread.run_sync(request)


def _cid_text(cid: bytes | str) -> str:
    if isinstance(cid, str):
        value = cid
    else:
        try:
            value = cid.decode("ascii")
        except UnicodeDecodeError as error:
            raise ValueError(
                "delegated routing requires a string-encoded CID"
            ) from error
    if not value:
        raise ValueError("CID must not be empty")
    return value


def _provider_records(payload: bytes) -> list[dict[str, Any]]:
    text = payload.decode("utf-8")
    try:
        document = json.loads(text)
    except json.JSONDecodeError:
        records = [json.loads(line) for line in text.splitlines() if line.strip()]
    else:
        if isinstance(document, dict):
            records = document.get("Providers") or []
        elif isinstance(document, list):
            records = document
        else:
            records = []

    return [record for record in records if isinstance(record, dict)]


def _peer_info(record: Mapping[str, Any]) -> PeerInfo:
    peer_id_value = record["ID"]
    if not isinstance(peer_id_value, str):
        raise ValueError("provider ID must be a string")

    addresses = record.get("Addrs") or []
    if not isinstance(addresses, list) or not all(
        isinstance(address, str) for address in addresses
    ):
        raise ValueError("provider addresses must be strings")

    return PeerInfo(
        _peer_id(peer_id_value),
        [Multiaddr(address) for address in addresses],
    )


def _peer_id(value: str) -> ID:
    if value and value[0].lower() in {"b", "k"}:
        try:
            raw = _decode_multibase(value)
            version, offset = _read_varint(raw, 0)
            codec, offset = _read_varint(raw, offset)
            if version == 1 and codec == 0x72:
                return ID(raw[offset:])
        except (ValueError, binascii.Error):
            pass

    try:
        return ID.from_base58(value)
    except ValueError:
        # The delegated API also permits a CIDv1 using the libp2p-key codec.
        raise ValueError("provider ID is not a supported peer ID")


def _decode_multibase(value: str) -> bytes:
    prefix = value[0].lower()
    encoded = value[1:]
    if prefix == "b":
        return base64.b32decode(encoded.upper() + "=" * (-len(encoded) % 8))
    number = 0
    for char in encoded.lower():
        digit = "0123456789abcdefghijklmnopqrstuvwxyz".find(char)
        if digit < 0:
            raise ValueError("invalid base36 peer ID")
        number = number * 36 + digit
    return number.to_bytes((number.bit_length() + 7) // 8, "big")


def _read_varint(data: bytes, offset: int) -> tuple[int, int]:
    value = 0
    shift = 0
    while offset < len(data):
        byte = data[offset]
        offset += 1
        value |= (byte & 0x7F) << shift
        if byte < 0x80:
            return value, offset
        shift += 7
        if shift >= 64:
            break
    raise ValueError("invalid varint")
