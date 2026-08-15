import pytest
from multiaddr import Multiaddr

from libp2p.crypto.ed25519 import create_new_key_pair
from libp2p.discovery.rendezvous.pb.rendezvous_pb2 import Message
from libp2p.discovery.rendezvous.rendezvous import (
    RendezvousPoint,
)
from libp2p.peer.envelope import seal_record
from libp2p.peer.id import ID
from libp2p.peer.peer_record import PeerRecord


class Host:
    def __init__(self):
        self.handler = None

    def set_stream_handler(self, protocol, handler):
        self.handler = handler


class Stream:
    def __init__(self, peer_id):
        self.muxed_conn = type("MuxedConn", (), {"peer_id": peer_id})()


def signed_record(seed: bytes):
    key_pair = create_new_key_pair(seed=seed)
    peer_id = ID.from_pubkey(key_pair.public_key)
    record = PeerRecord(
        peer_id,
        [Multiaddr("/ip4/127.0.0.1/tcp/4001")],
    )
    return peer_id, seal_record(
        record, key_pair.private_key
    ).marshal_envelope()


def register_message(namespace, signed, ttl=7200):
    return Message(
        type=Message.REGISTER,
        register=Message.Register(
            ns=namespace,
            signedPeerRecord=signed,
            ttl=ttl,
        ),
    )


def test_rendezvous_registers_and_discovers_by_namespace():
    host = Host()
    point = RendezvousPoint(host)
    peer_id, signed = signed_record(b"a" * 32)
    stream = Stream(peer_id)

    response = point._handle_message(register_message("app", signed), stream)
    assert response.registerResponse.status == Message.OK

    response = point._handle_message(
        Message(type=Message.DISCOVER, discover=Message.Discover(ns="app")),
        stream,
    )
    assert len(response.discoverResponse.registrations) == 1
    assert response.discoverResponse.registrations[0].signedPeerRecord == signed
    assert response.discoverResponse.cookie


def test_rendezvous_cookie_returns_only_new_registrations():
    point = RendezvousPoint(Host())
    first_id, first_record = signed_record(b"b" * 32)
    first_stream = Stream(first_id)
    point._handle_message(register_message("app", first_record), first_stream)
    first = point._handle_message(
        Message(type=Message.DISCOVER, discover=Message.Discover(ns="app")),
        first_stream,
    )

    second_id, second_record = signed_record(b"c" * 32)
    point._handle_message(register_message("app", second_record), Stream(second_id))
    second = point._handle_message(
        Message(
            type=Message.DISCOVER,
            discover=Message.Discover(ns="app", cookie=first.discoverResponse.cookie),
        ),
        first_stream,
    )

    assert [r.signedPeerRecord for r in second.discoverResponse.registrations] == [
        second_record
    ]


def test_rendezvous_rejects_invalid_signed_record():
    point = RendezvousPoint(Host())
    peer_id, _ = signed_record(b"d" * 32)

    response = point._handle_message(
        register_message("app", b"invalid"), Stream(peer_id)
    )

    assert response.registerResponse.status == Message.E_INVALID_SIGNED_PEER_RECORD


@pytest.mark.parametrize("namespace", ["", "x" * 256])
def test_rendezvous_rejects_invalid_namespace(namespace):
    point = RendezvousPoint(Host())
    peer_id, signed = signed_record(b"e" * 32)

    response = point._handle_message(
        register_message(namespace, signed), Stream(peer_id)
    )

    assert response.registerResponse.status == Message.E_INVALID_NAMESPACE
