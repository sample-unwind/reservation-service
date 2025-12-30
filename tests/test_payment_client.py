from unittest.mock import MagicMock, patch

import grpc
import pytest

import payment_pb2
from payment_client import (
    PaymentServiceError,
    get_payment_status,
    process_payment_for_reservation,
)


@patch("payment_client.grpc.insecure_channel")
def test_process_payment_success(mock_channel):
    """Test successful payment processing."""
    # Mock the gRPC response
    mock_response = payment_pb2.PaymentResponse(
        success=True, transaction_id="TXN-123", message="Payment processed successfully"
    )

    mock_stub = MagicMock()
    mock_stub.ProcessPayment.return_value = mock_response

    mock_channel_instance = MagicMock()
    mock_channel.return_value = mock_channel_instance
    mock_channel_instance.close = MagicMock()

    with patch("payment_client.payment_pb2_grpc.PaymentServiceStub") as mock_service:
        mock_service.return_value = mock_stub

        # Call the function
        success, transaction_id, message = process_payment_for_reservation(
            reservation_id="RES-001", user_id="USER-123", amount=100.0, currency="EUR"
        )

        # Assertions
        assert success is True
        assert transaction_id == "TXN-123"
        assert message == "Payment processed successfully"


@patch("payment_client.grpc.insecure_channel")
def test_process_payment_failure(mock_channel):
    """Test failed payment processing."""
    # Mock the gRPC response with failure
    mock_response = payment_pb2.PaymentResponse(
        success=False, transaction_id="", message="Insufficient funds"
    )

    mock_stub = MagicMock()
    mock_stub.ProcessPayment.return_value = mock_response

    mock_channel_instance = MagicMock()
    mock_channel.return_value = mock_channel_instance
    mock_channel_instance.close = MagicMock()

    with patch("payment_client.payment_pb2_grpc.PaymentServiceStub") as mock_service:
        mock_service.return_value = mock_stub

        # Call the function
        success, transaction_id, message = process_payment_for_reservation(
            reservation_id="RES-002", user_id="USER-123", amount=1000.0, currency="EUR"
        )

        # Assertions
        assert success is False
        assert transaction_id == ""
        assert message == "Insufficient funds"


@patch("payment_client.grpc.insecure_channel")
def test_process_payment_grpc_timeout(mock_channel):
    """Test gRPC timeout handling with retries."""

    # Create a proper gRPC RpcError
    class MockRpcError(grpc.RpcError):
        def code(self):
            return grpc.StatusCode.DEADLINE_EXCEEDED

        def details(self):
            return "Timeout"

    mock_stub = MagicMock()
    mock_stub.ProcessPayment.side_effect = MockRpcError()

    mock_channel_instance = MagicMock()
    mock_channel.return_value = mock_channel_instance
    mock_channel_instance.close = MagicMock()

    with patch("payment_client.payment_pb2_grpc.PaymentServiceStub") as mock_service:
        mock_service.return_value = mock_stub

        # Call should raise PaymentServiceError after retries
        with pytest.raises(PaymentServiceError):
            process_payment_for_reservation(
                reservation_id="RES-003",
                user_id="USER-123",
                amount=100.0,
                currency="EUR",
            )


@patch("payment_client.grpc.insecure_channel")
def test_process_payment_invalid_argument_no_retry(mock_channel):
    """Test that invalid argument errors are not retried."""

    # Create a proper gRPC RpcError
    class MockRpcError(grpc.RpcError):
        def code(self):
            return grpc.StatusCode.INVALID_ARGUMENT

        def details(self):
            return "Invalid currency"

    mock_stub = MagicMock()
    mock_stub.ProcessPayment.side_effect = MockRpcError()

    mock_channel_instance = MagicMock()
    mock_channel.return_value = mock_channel_instance
    mock_channel_instance.close = MagicMock()

    with patch("payment_client.payment_pb2_grpc.PaymentServiceStub") as mock_service:
        mock_service.return_value = mock_stub

        # Call should return failure immediately without retries
        success, transaction_id, message = process_payment_for_reservation(
            reservation_id="RES-004", user_id="USER-123", amount=100.0, currency="XYZ"
        )

        assert success is False
        assert "Invalid currency" in message


@patch("payment_client.grpc.insecure_channel")
def test_get_payment_status_success(mock_channel):
    """Test getting payment status successfully."""
    # Mock the gRPC response
    mock_response = payment_pb2.PaymentStatusResponse(
        status="COMPLETED", transaction_id="TXN-123"
    )

    mock_stub = MagicMock()
    mock_stub.GetPaymentStatus.return_value = mock_response

    mock_channel_instance = MagicMock()
    mock_channel.return_value = mock_channel_instance
    mock_channel_instance.close = MagicMock()

    with patch("payment_client.payment_pb2_grpc.PaymentServiceStub") as mock_service:
        mock_service.return_value = mock_stub

        # Call the function
        status, transaction_id = get_payment_status(transaction_id="TXN-123")

        # Assertions
        assert status == "COMPLETED"
        assert transaction_id == "TXN-123"


@patch("payment_client.grpc.insecure_channel")
def test_get_payment_status_error(mock_channel):
    """Test error handling when getting payment status."""

    # Create a proper gRPC RpcError
    class MockRpcError(grpc.RpcError):
        def code(self):
            return grpc.StatusCode.NOT_FOUND

        def details(self):
            return "Transaction not found"

    mock_stub = MagicMock()
    mock_stub.GetPaymentStatus.side_effect = MockRpcError()

    mock_channel_instance = MagicMock()
    mock_channel.return_value = mock_channel_instance
    mock_channel_instance.close = MagicMock()

    with patch("payment_client.payment_pb2_grpc.PaymentServiceStub") as mock_service:
        mock_service.return_value = mock_stub

        # Call should raise PaymentServiceError
        with pytest.raises(PaymentServiceError):
            get_payment_status(transaction_id="TXN-INVALID")
