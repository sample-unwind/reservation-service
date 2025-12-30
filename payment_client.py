import logging
from typing import Tuple

import grpc
from grpc import RpcError

import payment_pb2
import payment_pb2_grpc
from config import get_payment_service_host, get_payment_service_port

logger = logging.getLogger(__name__)

# Configuration
GRPC_TIMEOUT = 5.0  # 5 seconds timeout
MAX_RETRIES = 3


class PaymentServiceError(Exception):
    """Exception raised when payment service is unavailable or returns an error."""

    pass


def process_payment_for_reservation(
    reservation_id: str, user_id: str, amount: float, currency: str = "EUR"
) -> Tuple[bool, str, str]:
    """
    Call payment-service to process payment via gRPC.

    Args:
        reservation_id: The reservation ID
        user_id: The user ID
        amount: Payment amount
        currency: Currency code (default: EUR)

    Returns:
        Tuple of (success, transaction_id, message)

    Raises:
        PaymentServiceError: When payment service is unavailable after retries
    """
    host = get_payment_service_host()
    port = get_payment_service_port()
    address = f"{host}:{port}"

    last_error = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            logger.info(
                f"Attempting payment processing (attempt {attempt}/{MAX_RETRIES}) "
                f"for reservation {reservation_id}"
            )

            # Create insecure channel (use secure channel in production)
            channel = grpc.insecure_channel(address)
            stub = payment_pb2_grpc.PaymentServiceStub(channel)

            # Create request
            request = payment_pb2.PaymentRequest(
                reservation_id=reservation_id,
                user_id=user_id,
                amount=amount,
                currency=currency,
            )

            # Call ProcessPayment with timeout
            response = stub.ProcessPayment(request, timeout=GRPC_TIMEOUT)

            # Close channel
            channel.close()

            logger.info(
                f"Payment processing {'succeeded' if response.success else 'failed'} "
                f"for reservation {reservation_id}: {response.message}"
            )

            return response.success, response.transaction_id, response.message

        except RpcError as e:
            last_error = e
            logger.warning(
                f"gRPC error on attempt {attempt}/{MAX_RETRIES} "
                f"for reservation {reservation_id}: {e.code()} - {e.details()}"
            )

            # Don't retry on specific error codes
            if e.code() in [
                grpc.StatusCode.INVALID_ARGUMENT,
                grpc.StatusCode.ALREADY_EXISTS,
            ]:
                return False, "", f"Payment failed: {e.details()}"

            if attempt == MAX_RETRIES:
                break

        except Exception as e:
            last_error = e
            logger.error(
                f"Unexpected error on attempt {attempt}/{MAX_RETRIES} "
                f"for reservation {reservation_id}: {str(e)}"
            )

            if attempt == MAX_RETRIES:
                break

    # All retries failed
    error_msg = (
        f"Payment service unavailable after {MAX_RETRIES} attempts: {str(last_error)}"
    )
    logger.error(error_msg)
    raise PaymentServiceError(error_msg)


def get_payment_status(transaction_id: str) -> Tuple[str, str]:
    """
    Get payment status from payment-service via gRPC.

    Args:
        transaction_id: The transaction ID

    Returns:
        Tuple of (status, transaction_id)

    Raises:
        PaymentServiceError: When payment service is unavailable
    """
    host = get_payment_service_host()
    port = get_payment_service_port()
    address = f"{host}:{port}"

    try:
        logger.info(f"Getting payment status for transaction {transaction_id}")

        channel = grpc.insecure_channel(address)
        stub = payment_pb2_grpc.PaymentServiceStub(channel)

        request = payment_pb2.PaymentStatusRequest(transaction_id=transaction_id)

        response = stub.GetPaymentStatus(request, timeout=GRPC_TIMEOUT)

        channel.close()

        logger.info(f"Payment status for {transaction_id}: {response.status}")

        return response.status, response.transaction_id

    except RpcError as e:
        error_msg = f"Failed to get payment status: {e.code()} - {e.details()}"
        logger.error(error_msg)
        raise PaymentServiceError(error_msg)
