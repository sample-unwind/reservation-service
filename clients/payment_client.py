"""
Payment Service gRPC Client

gRPC client for communicating with the payment-service microservice.
Provides methods for processing payments and refunds for reservations.
"""

import logging
import os
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import grpc

from clients import payment_pb2, payment_pb2_grpc

logger = logging.getLogger(__name__)

# Service configuration
PAYMENT_SERVICE_HOST = os.getenv("PAYMENT_SERVICE_HOST", "payment-service")
PAYMENT_SERVICE_PORT = int(os.getenv("PAYMENT_SERVICE_PORT", "50051"))

# gRPC timeout in seconds
GRPC_TIMEOUT = float(os.getenv("GRPC_TIMEOUT", "30.0"))


@dataclass
class PaymentRequest:
    """Payment request data."""

    reservation_id: UUID
    user_id: UUID
    tenant_id: UUID
    amount: float
    currency: str = "EUR"


@dataclass
class PaymentResponse:
    """Payment response data."""

    success: bool
    transaction_id: str | None
    message: str
    error_code: str | None = None


@dataclass
class RefundRequest:
    """Refund request data."""

    transaction_id: str
    tenant_id: UUID
    amount: float = 0.0  # 0 means full refund
    reason: str = "Cancellation refund"


@dataclass
class RefundResponse:
    """Refund response data."""

    success: bool
    refund_id: str | None
    message: str
    error_code: str | None = None


@dataclass
class PaymentStatusResponse:
    """Payment status response data."""

    status: str
    transaction_id: str
    amount: float
    currency: str
    created_at: str


class PaymentServiceError(Exception):
    """Exception raised when payment service communication fails."""

    def __init__(self, message: str, error_code: str | None = None):
        super().__init__(message)
        self.error_code = error_code


class PaymentServiceUnavailableError(PaymentServiceError):
    """Exception raised when payment service is unavailable."""

    pass


class PaymentClient:
    """
    gRPC client for payment-service.

    Handles connection management and provides typed methods
    for all payment operations.
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
        self._channel: grpc.Channel | None = None
        self._stub: payment_pb2_grpc.PaymentServiceStub | None = None
        logger.info(f"Payment client configured for {host}:{port}")

    def connect(self) -> None:
        """Establish gRPC connection to payment service."""
        if self._channel is not None:
            logger.debug("Already connected to payment service")
            return

        target = f"{self.host}:{self.port}"
        logger.info(f"Connecting to payment service at {target}")

        # Create insecure channel (use secure channel in production with TLS)
        self._channel = grpc.insecure_channel(
            target,
            options=[
                ("grpc.keepalive_time_ms", 30000),
                ("grpc.keepalive_timeout_ms", 10000),
                ("grpc.keepalive_permit_without_calls", True),
                ("grpc.http2.max_pings_without_data", 0),
            ],
        )
        self._stub = payment_pb2_grpc.PaymentServiceStub(self._channel)
        logger.info("Connected to payment service")

    def close(self) -> None:
        """Close gRPC connection."""
        if self._channel:
            self._channel.close()
            self._channel = None
            self._stub = None
            logger.info("Disconnected from payment service")

    def __enter__(self) -> "PaymentClient":
        """Context manager entry."""
        self.connect()
        return self

    def __exit__(self, *args: Any) -> None:
        """Context manager exit."""
        self.close()

    def _ensure_connected(self) -> None:
        """Ensure the client is connected."""
        if self._stub is None:
            self.connect()

    def process_payment(self, request: PaymentRequest) -> PaymentResponse:
        """
        Process a payment for a reservation.

        Args:
            request: Payment request data

        Returns:
            PaymentResponse with transaction result

        Raises:
            PaymentServiceUnavailableError: If service is unavailable
            PaymentServiceError: If payment fails
        """
        self._ensure_connected()

        logger.info(
            f"Processing payment for reservation {request.reservation_id}: "
            f"{request.amount} {request.currency}"
        )

        grpc_request = payment_pb2.PaymentRequest(
            reservation_id=str(request.reservation_id),
            user_id=str(request.user_id),
            amount=request.amount,
            currency=request.currency,
            tenant_id=str(request.tenant_id),
        )

        try:
            grpc_response = self._stub.ProcessPayment(
                grpc_request, timeout=GRPC_TIMEOUT
            )

            if grpc_response.success:
                logger.info(
                    f"Payment processed successfully: {grpc_response.transaction_id}"
                )
            else:
                logger.warning(
                    f"Payment failed: {grpc_response.message} "
                    f"(error_code={grpc_response.error_code})"
                )

            return PaymentResponse(
                success=grpc_response.success,
                transaction_id=(
                    grpc_response.transaction_id
                    if grpc_response.transaction_id
                    else None
                ),
                message=grpc_response.message,
                error_code=(
                    grpc_response.error_code if grpc_response.error_code else None
                ),
            )

        except grpc.RpcError as e:
            logger.error(f"gRPC error during payment processing: {e}")
            if e.code() == grpc.StatusCode.UNAVAILABLE:
                raise PaymentServiceUnavailableError(
                    "Payment service is unavailable"
                ) from e
            raise PaymentServiceError(
                f"Payment processing failed: {e.details()}"
            ) from e

    def refund_payment(self, request: RefundRequest) -> RefundResponse:
        """
        Refund a previous payment.

        Args:
            request: Refund request data

        Returns:
            RefundResponse with refund result

        Raises:
            PaymentServiceUnavailableError: If service is unavailable
            PaymentServiceError: If refund fails
        """
        self._ensure_connected()

        logger.info(
            f"Processing refund for transaction {request.transaction_id}"
            + (f" (amount: {request.amount})" if request.amount > 0 else " (full)")
        )

        grpc_request = payment_pb2.RefundRequest(
            transaction_id=request.transaction_id,
            amount=request.amount,
            reason=request.reason,
            tenant_id=str(request.tenant_id),
        )

        try:
            grpc_response = self._stub.RefundPayment(grpc_request, timeout=GRPC_TIMEOUT)

            if grpc_response.success:
                logger.info(f"Refund processed successfully: {grpc_response.refund_id}")
            else:
                logger.warning(
                    f"Refund failed: {grpc_response.message} "
                    f"(error_code={grpc_response.error_code})"
                )

            return RefundResponse(
                success=grpc_response.success,
                refund_id=grpc_response.refund_id if grpc_response.refund_id else None,
                message=grpc_response.message,
                error_code=(
                    grpc_response.error_code if grpc_response.error_code else None
                ),
            )

        except grpc.RpcError as e:
            logger.error(f"gRPC error during refund processing: {e}")
            if e.code() == grpc.StatusCode.UNAVAILABLE:
                raise PaymentServiceUnavailableError(
                    "Payment service is unavailable"
                ) from e
            raise PaymentServiceError(f"Refund processing failed: {e.details()}") from e

    def get_payment_status(self, transaction_id: str) -> PaymentStatusResponse:
        """
        Check the status of a payment.

        Args:
            transaction_id: Transaction ID to check

        Returns:
            PaymentStatusResponse with status details

        Raises:
            PaymentServiceUnavailableError: If service is unavailable
            PaymentServiceError: If status check fails
        """
        self._ensure_connected()

        logger.info(f"Checking payment status for {transaction_id}")

        grpc_request = payment_pb2.PaymentStatusRequest(
            transaction_id=transaction_id,
        )

        try:
            grpc_response = self._stub.GetPaymentStatus(
                grpc_request, timeout=GRPC_TIMEOUT
            )

            return PaymentStatusResponse(
                status=grpc_response.status,
                transaction_id=grpc_response.transaction_id,
                amount=grpc_response.amount,
                currency=grpc_response.currency,
                created_at=grpc_response.created_at,
            )

        except grpc.RpcError as e:
            logger.error(f"gRPC error during status check: {e}")
            if e.code() == grpc.StatusCode.UNAVAILABLE:
                raise PaymentServiceUnavailableError(
                    "Payment service is unavailable"
                ) from e
            if e.code() == grpc.StatusCode.NOT_FOUND:
                raise PaymentServiceError(
                    "Payment not found", error_code="PAYMENT_NOT_FOUND"
                ) from e
            raise PaymentServiceError(f"Status check failed: {e.details()}") from e


# Singleton instance for convenience
_client: PaymentClient | None = None


def get_payment_client() -> PaymentClient:
    """
    Get or create a singleton payment client.

    Returns:
        PaymentClient instance (connected)
    """
    global _client
    if _client is None:
        _client = PaymentClient()
        _client.connect()
    return _client


def close_payment_client() -> None:
    """Close the singleton payment client connection."""
    global _client
    if _client is not None:
        _client.close()
        _client = None
