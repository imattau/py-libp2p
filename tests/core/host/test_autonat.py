from unittest.mock import (
    AsyncMock,
    patch,
)

import pytest
from multiaddr import Multiaddr

from libp2p.host.autonat.autonat import (
    AUTONAT_PROTOCOL_ID,
    AutoNATService,
    AutoNATStatus,
)
from libp2p.host.autonat.pb.autonat_pb2 import Message
from libp2p.network.stream.exceptions import (
    StreamError,
)
from libp2p.network.stream.net_stream import (
    NetStream,
)
from libp2p.peer.id import (
    ID,
)
from libp2p.utils.varint import encode_varint_prefixed
from tests.utils.factories import (
    HostFactory,
)


@pytest.mark.trio
async def test_autonat_service_initialization():
    """Test that the AutoNAT service initializes correctly."""
    async with HostFactory.create_batch_and_listen(1) as hosts:
        host = hosts[0]
        service = AutoNATService(host)

        assert service.status == AutoNATStatus.UNKNOWN
        assert service.dial_results == {}
        assert service.host == host
        assert service.peerstore == host.get_peerstore()
        assert AUTONAT_PROTOCOL_ID in host.get_mux().handlers


@pytest.mark.trio
async def test_autonat_status_getter():
    """Test that the AutoNAT status getter works correctly."""
    async with HostFactory.create_batch_and_listen(1) as hosts:
        host = hosts[0]
        service = AutoNATService(host)

        # Testing the initial status
        assert service.get_status() == AutoNATStatus.UNKNOWN

        # Testing the status changes
        service.status = AutoNATStatus.PUBLIC
        assert service.get_status() == AutoNATStatus.PUBLIC

        service.status = AutoNATStatus.PRIVATE
        assert service.get_status() == AutoNATStatus.PRIVATE


@pytest.mark.trio
async def test_update_status():
    """Test that the AutoNAT status updates correctly based on dial results."""
    async with HostFactory.create_batch_and_listen(1) as hosts:
        host = hosts[0]
        service = AutoNATService(host)

        # No dial results should result in UNKNOWN status
        service.update_status()
        assert service.status == AutoNATStatus.UNKNOWN

        # Less than 2 successful dials should result in PRIVATE status
        service.dial_results = {
            ID(b"peer1"): True,
            ID(b"peer2"): False,
            ID(b"peer3"): False,
        }
        service.update_status()
        assert service.status == AutoNATStatus.PRIVATE

        # 2 or more successful dials should result in PUBLIC status
        service.dial_results = {
            ID(b"peer1"): True,
            ID(b"peer2"): True,
            ID(b"peer3"): False,
        }
        service.update_status()
        assert service.status == AutoNATStatus.PUBLIC


@pytest.mark.trio
async def test_try_dial():
    """Test that the try_dial method works correctly."""
    async with HostFactory.create_batch_and_listen(2) as hosts:
        host1, host2 = hosts
        service = AutoNATService(host1)
        peer_id = host2.get_id()

        # Test successful dial
        with patch.object(
            host1, "new_stream", new_callable=AsyncMock
        ) as mock_new_stream:
            mock_stream = AsyncMock(spec=NetStream)
            mock_new_stream.return_value = mock_stream

            result = await service._try_dial(peer_id)

            assert result is True
            mock_new_stream.assert_called_once_with(peer_id, [AUTONAT_PROTOCOL_ID])

            mock_stream.close.assert_called_once()

        # Test failed dial
        with patch.object(
            host1, "new_stream", new_callable=AsyncMock
        ) as mock_new_stream:
            mock_new_stream.side_effect = Exception("Connection failed")

            result = await service._try_dial(peer_id)

            assert result is False
            mock_new_stream.assert_called_once_with(peer_id, [AUTONAT_PROTOCOL_ID])


@pytest.mark.trio
async def test_probe_sends_addresses_and_records_result():
    async with HostFactory.create_batch_and_listen(2) as hosts:
        host1, host2 = hosts
        service = AutoNATService(host1)
        mock_stream = AsyncMock(spec=NetStream)
        response = Message(type=Message.DIAL_RESPONSE)
        response.dialResponse.status = Message.OK
        encoded_response = encode_varint_prefixed(response.SerializeToString())
        mock_stream.read.side_effect = [encoded_response[:1], encoded_response[1:]]

        with patch.object(
            host1, "new_stream", new_callable=AsyncMock, return_value=mock_stream
        ) as mock_new_stream:
            result = await service.probe(
                host2.get_id(), [Multiaddr("/ip4/127.0.0.1/tcp/4001")]
            )

        assert result is True
        assert service.dial_results[host2.get_id()] is True
        mock_new_stream.assert_awaited_once_with(
            host2.get_id(), [AUTONAT_PROTOCOL_ID]
        )
        encoded_request = mock_stream.write.call_args.args[0]
        request = Message.FromString(encoded_request[1:])
        assert request.dial.peer.id == host1.get_id().to_bytes()
        assert list(request.dial.peer.addrs) == [b"/ip4/127.0.0.1/tcp/4001"]
        mock_stream.close.assert_awaited_once()


@pytest.mark.trio
async def test_handle_dial():
    """Test that the handle_dial method works correctly."""
    async with HostFactory.create_batch_and_listen(2) as hosts:
        host1, host2 = hosts
        service = AutoNATService(host1)
        peer_id = host2.get_id()

        # Create a mock message with a peer to dial
        message = Message(type=Message.DIAL)
        peer_info = message.dial.peer
        peer_info.id = peer_id.to_bytes()
        peer_info.addrs.extend([b"/ip4/127.0.0.1/tcp/4001"])

        # Mock the _try_dial method
        with patch.object(
            service, "_try_dial", new_callable=AsyncMock
        ) as mock_try_dial:
            mock_try_dial.return_value = True

            response = await service._handle_dial(message)

            assert response.type == Message.DIAL_RESPONSE
            assert response.dialResponse.status == Message.OK
            mock_try_dial.assert_called_once_with(peer_id)


@pytest.mark.trio
async def test_handle_dial_refuses_address_for_different_ip():
    async with HostFactory.create_batch_and_listen(1) as hosts:
        service = AutoNATService(hosts[0])
        message = Message(type=Message.DIAL)
        message.dial.peer.id = b"peer_id"
        message.dial.peer.addrs.append(b"/ip4/198.51.100.1/tcp/4001")

        with patch.object(service, "_try_dial", new_callable=AsyncMock) as dial:
            response = await service._handle_dial(message, ("127.0.0.1", 4000))

        assert response.dialResponse.status == Message.E_DIAL_REFUSED
        dial.assert_not_awaited()


@pytest.mark.trio
async def test_handle_request():
    """Test that the handle_request method works correctly."""
    async with HostFactory.create_batch_and_listen(1) as hosts:
        host = hosts[0]
        service = AutoNATService(host)

        # Test handling a DIAL request
        message = Message(type=Message.DIAL)
        message.dial.peer.id = b"peer_id"

        with patch.object(
            service, "_handle_dial", new_callable=AsyncMock
        ) as mock_handle_dial:
            mock_handle_dial.return_value = Message()

            response = await service._handle_request(message.SerializeToString())

            mock_handle_dial.assert_called_once()
            assert isinstance(response, Message)

        # Test handling an unknown request type
        message = Message()
        message.type = Message.DIAL_RESPONSE

        response = await service._handle_request(message.SerializeToString())

        assert isinstance(response, Message)
        assert response.type == Message.DIAL_RESPONSE
        assert response.dialResponse.status == Message.E_BAD_REQUEST


@pytest.mark.trio
async def test_handle_stream():
    """Test that handle_stream correctly processes stream data."""
    async with HostFactory.create_batch_and_listen(1) as hosts:
        host = hosts[0]
        autonat_service = AutoNATService(host)

        # Create a mock stream
        mock_stream = AsyncMock(spec=NetStream)

        # Create a properly initialized request Message
        request = Message(type=Message.DIAL)
        request.dial.peer.id = b"peer_id"
        request.dial.peer.addrs.append(b"addr1")

        # Create a properly initialized response Message
        response = Message(type=Message.DIAL_RESPONSE)
        response.dialResponse.status = Message.OK

        # Mock stream read/write and _handle_request
        encoded_request = encode_varint_prefixed(request.SerializeToString())
        mock_stream.read.side_effect = [encoded_request[:1], encoded_request[1:]]
        mock_stream.get_remote_address.return_value = ("127.0.0.1", 4000)
        mock_stream.write.return_value = None
        autonat_service._handle_request = AsyncMock(return_value=response)

        # Test successful stream handling
        await autonat_service.handle_stream(mock_stream)
        assert mock_stream.read.await_count == 2
        mock_stream.write.assert_called_once_with(
            encode_varint_prefixed(response.SerializeToString())
        )
        mock_stream.close.assert_called_once()

        # Test stream error handling
        mock_stream.reset_mock()
        mock_stream.read.side_effect = StreamError("Stream error")
        await autonat_service.handle_stream(mock_stream)
        mock_stream.close.assert_called_once()

        # Requests without an observable remote address must be refused.
        mock_stream.reset_mock()
        mock_stream.read.side_effect = [encoded_request[:1], encoded_request[1:]]
        mock_stream.get_remote_address.return_value = None
        refused = Message(type=Message.DIAL_RESPONSE)
        refused.dialResponse.status = Message.E_DIAL_REFUSED
        await autonat_service.handle_stream(mock_stream)
        mock_stream.write.assert_called_once_with(
            encode_varint_prefixed(refused.SerializeToString())
        )
        mock_stream.close.assert_called_once()
