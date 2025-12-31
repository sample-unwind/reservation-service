"""
Payment Service Client

gRPC client for communicating with the payment-service microservice.
Provides methods for processing payments for reservations.

Note: This is a simplified implementation. In production, you would
use actual gRPC stubs generated from .proto files.
"""

import logging
import os
from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

logger = logging.getLogger(__name__)

# Service configuration
PAYMENT_SERVICE_HOST = os.getenv("PAYMENT_SERVICE_HOST", "payment-service")
PAYMENT_SERVICE_PORT = int(os.getenv("PAYMENT_SERVICE_PORT", "50051"))


@dataclass
class PaymentRequest:
    """Payment request data."""

    reservation_id: UUID
    user_id: UUID
    amount: float
    currency: str = "EUR"
    description: str = ""


@dataclass
class PaymentResponse:
    """Payment response data."""

    success: bool
    transaction_id: UUID | None
    message: str
    error_code: str | None = None


class PaymentServiceError(Exception):
    """Exception raised when payment service communication fails."""

    pass


class PaymentClient:
    """
    Client for payment-service.

    In production, this would use gRPC stubs generated from .proto files.
    Currently implements a mock/stub version for development.
    """

    def __init__(
        self,
        host: str = PAYMENT_SERVICE_HOST,
        port: int = PAYMENT_SERVICE_PORT,
    ):
        """
        Initialize payment client.

        Args:
            host: Payment service hostname
            port: Payment service gRPC port
        """
        self.host = host
        self.port = port
        self._channel = None
        self._stub = None
        logger.info(f"Payment client configured for {host}:{port}")

    def connect(self) -> None:
        """
        Establish gRPC connection to payment service.

        Note: This is a stub implementation. In production, use:
            self._channel = grpc.insecure_channel(f"{self.host}:{self.port}")
            self._stub = payment_pb2_grpc.PaymentServiceStub(self._channel)
        """
        logger.info(f"Connecting to payment service at {self.host}:{self.port}")
        # In production:
        # import grpc
        # from proto import payment_pb2_grpc
        # self._channel = grpc.insecure_channel(f"{self.host}:{self.port}")
        # self._stub = payment_pb2_grpc.PaymentServiceStub(self._channel)

    def close(self) -> None:
        """Close gRPC connection."""
        if self._channel:
            self._channel.close()
            self._channel = None
            self._stub = None

    def __enter__(self) -> "PaymentClient":
        """Context manager entry."""
        self.connect()
        return self

    def __exit__(self, *args: Any) -> None:
        """Context manager exit."""
        self.close()

    def process_payment(self, request: PaymentRequest) -> PaymentResponse:
        """
        Process a payment for a reservation.

        Args:
            request: Payment request data

        Returns:
            PaymentResponse with transaction result

        Note: This is a mock implementation that always succeeds.
        In production, this would make an actual gRPC call.
        """
        logger.info(
            f"Processing payment for reservation {request.reservation_id}: "
            f"{request.amount} {request.currency}"
        )

        try:
            # Mock implementation - always succeeds
            # In production:
            # grpc_request = payment_pb2.PaymentRequest(
            #     reservation_id=str(request.reservation_id),
            #     user_id=str(request.user_id),
            #     amount=request.amount,
            #     currency=request.currency,
            #     description=request.description,
            # )
            # grpc_response = self._stub.ProcessPayment(grpc_request)
            # return PaymentResponse(
            #     success=grpc_response.success,
            #     transaction_id=UUID(grpc_response.transaction_id),
            #     message=grpc_response.message,
            #     error_code=grpc_response.error_code or None,
            # )

            # Mock response
            transaction_id = uuid4()
            logger.info(f"Payment processed successfully: {transaction_id}")

            return PaymentResponse(
                success=True,
                transaction_id=transaction_id,
                message="Payment processed successfully",
            )

        except Exception as e:
            logger.error(f"Payment processing failed: {e}")
            return PaymentResponse(
                success=False,
                transaction_id=None,
                message=f"Payment failed: {str(e)}",
                error_code="PAYMENT_FAILED",
            )

    def refund_payment(
        self,
        transaction_id: UUID,
        amount: float | None = None,
    ) -> PaymentResponse:
        """
        Refund a previous payment.

        Args:
            transaction_id: Original transaction ID
            amount: Partial refund amount (None for full refund)

        Returns:
            PaymentResponse with refund result
        """
        logger.info(
            f"Processing refund for transaction {transaction_id}"
            + (f" (amount: {amount})" if amount else " (full refund)")
        )

        try:
            # Mock implementation
            refund_id = uuid4()
            logger.info(f"Refund processed successfully: {refund_id}")

            return PaymentResponse(
                success=True,
                transaction_id=refund_id,
                message="Refund processed successfully",
            )

        except Exception as e:
            logger.error(f"Refund processing failed: {e}")
            return PaymentResponse(
                success=False,
                transaction_id=None,
                message=f"Refund failed: {str(e)}",
                error_code="REFUND_FAILED",
            )

    def check_payment_status(self, transaction_id: UUID) -> dict[str, Any]:
        """
        Check the status of a payment.

        Args:
            transaction_id: Transaction ID to check

        Returns:
            Payment status dictionary
        """
        logger.info(f"Checking payment status for {transaction_id}")

        # Mock implementation
        return {
            "transaction_id": str(transaction_id),
            "status": "COMPLETED",
            "created_at": "2024-01-01T00:00:00Z",
        }


# Singleton instance for convenience
_client: PaymentClient | None = None


def get_payment_client() -> PaymentClient:
    """
    Get or create a singleton payment client.

    Returns:
        PaymentClient instance
    """
    global _client
    if _client is None:
        _client = PaymentClient()
        _client.connect()
    return _client
