import os


def get_payment_service_host() -> str:
    """Get payment service host from environment variable."""
    return os.getenv("PAYMENT_SERVICE_HOST", "payment-service")


def get_payment_service_port() -> int:
    """Get payment service port from environment variable."""
    return int(os.getenv("PAYMENT_SERVICE_PORT", "50051"))
