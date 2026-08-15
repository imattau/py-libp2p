"""
Typing declarations for the generated AutoNAT protobuf module.

The declarations mirror autonat.proto. They are kept here because the
protobuf stub generator is not part of the runtime dependency set.
"""

import builtins
import collections.abc
import google.protobuf.descriptor
import google.protobuf.internal.containers
import google.protobuf.internal.enum_type_wrapper
import google.protobuf.message
import typing

DESCRIPTOR: google.protobuf.descriptor.FileDescriptor


class Message(google.protobuf.message.Message):
    DESCRIPTOR: google.protobuf.descriptor.Descriptor

    class MessageType:
        ValueType: typing.TypeAlias = builtins.int
        DIAL: ValueType
        DIAL_RESPONSE: ValueType

    class ResponseStatus:
        ValueType: typing.TypeAlias = builtins.int
        OK: ValueType
        E_DIAL_ERROR: ValueType
        E_DIAL_REFUSED: ValueType
        E_BAD_REQUEST: ValueType
        E_INTERNAL_ERROR: ValueType

    class PeerInfo(google.protobuf.message.Message):
        DESCRIPTOR: google.protobuf.descriptor.Descriptor
        id: builtins.bytes

        @property
        def addrs(
            self,
        ) -> google.protobuf.internal.containers.RepeatedScalarFieldContainer[
            builtins.bytes
        ]: ...

        def __init__(
            self,
            *,
            id: builtins.bytes = ...,
            addrs: collections.abc.Iterable[builtins.bytes] | None = ...,
        ) -> None: ...

    class Dial(google.protobuf.message.Message):
        DESCRIPTOR: google.protobuf.descriptor.Descriptor

        @property
        def peer(self) -> Message.PeerInfo: ...

        def __init__(
            self,
            *,
            peer: Message.PeerInfo | None = ...,
        ) -> None: ...

    class DialResponse(google.protobuf.message.Message):
        DESCRIPTOR: google.protobuf.descriptor.Descriptor
        status: Message.ResponseStatus.ValueType
        statusText: builtins.str
        addr: builtins.bytes

        def __init__(
            self,
            *,
            status: Message.ResponseStatus.ValueType = ...,
            statusText: builtins.str = ...,
            addr: builtins.bytes = ...,
        ) -> None: ...

    TYPE_FIELD_NUMBER: builtins.int
    DIAL_FIELD_NUMBER: builtins.int
    DIAL_RESPONSE_FIELD_NUMBER: builtins.int
    DIAL: MessageType.ValueType
    DIAL_RESPONSE: MessageType.ValueType
    OK: ResponseStatus.ValueType
    E_DIAL_ERROR: ResponseStatus.ValueType
    E_DIAL_REFUSED: ResponseStatus.ValueType
    E_BAD_REQUEST: ResponseStatus.ValueType
    E_INTERNAL_ERROR: ResponseStatus.ValueType
    type: Message.MessageType.ValueType

    @property
    def dial(self) -> Message.Dial: ...

    @property
    def dialResponse(self) -> Message.DialResponse: ...

    def __init__(
        self,
        *,
        type: Message.MessageType.ValueType = ...,
        dial: Message.Dial | None = ...,
        dialResponse: Message.DialResponse | None = ...,
    ) -> None: ...

    def HasField(
        self,
        field_name: typing.Literal[
            "dial",
            b"dial",
            "dialResponse",
            b"dialResponse",
            "type",
            b"type",
        ],
    ) -> builtins.bool: ...

    def ClearField(
        self,
        field_name: typing.Literal[
            "dial",
            b"dial",
            "dialResponse",
            b"dialResponse",
            "type",
            b"type",
        ],
    ) -> None: ...
