# -*- coding: utf-8 -*-
# Generated-compatible protobuf bindings for holepunch.proto.
"""Protocol buffer messages for the libp2p DCUtR protocol."""
from google.protobuf import descriptor as _descriptor
from google.protobuf import descriptor_pool as _descriptor_pool
from google.protobuf import symbol_database as _symbol_database
from google.protobuf.internal import builder as _builder

_sym_db = _symbol_database.Default()

DESCRIPTOR = _descriptor_pool.Default().AddSerializedFile(
    b'\n\x0fholepunch.proto\x12\x0cholepunch.pb"i\n\tHolePunch\x12*\n\x04type\x18\x01 \x02(\x0e2\x1c.holepunch.pb.HolePunch.Type\x12\x10\n\x08ObsAddrs\x18\x02 \x03(\x0c"\x1e\n\x04Type\x12\x0b\n\x07CONNECT\x10d\x12\t\n\x04SYNC\x10\xac\x02b\x06proto2'
)

_globals = globals()
_builder.BuildMessageAndEnumDescriptors(DESCRIPTOR, _globals)
_builder.BuildTopDescriptorsAndMessages(DESCRIPTOR, "holepunch_pb2", _globals)
