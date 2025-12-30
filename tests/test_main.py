from unittest.mock import patch

from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


def test_health_live():
    response = client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "alive"}


def test_health_ready():
    response = client.get("/health/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


def test_root():
    response = client.get("/")
    assert response.status_code == 200
    assert "message" in response.json()


@patch("main.process_payment_for_reservation")
def test_create_reservation_success(mock_payment):
    """Test successful reservation creation with payment."""
    # Mock successful payment
    mock_payment.return_value = (True, "TXN-123", "Payment successful")

    response = client.post(
        "/reservations",
        json={"user_id": "USER-001", "amount": 100.0, "currency": "EUR"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "RESERVATION_CONFIRMED"
    assert data["transaction_id"] == "TXN-123"
    assert "RES-" in data["reservation_id"]


@patch("main.process_payment_for_reservation")
def test_create_reservation_payment_failed(mock_payment):
    """Test reservation creation when payment fails."""
    # Mock failed payment
    mock_payment.return_value = (False, "", "Insufficient funds")

    response = client.post(
        "/reservations",
        json={"user_id": "USER-002", "amount": 1000.0, "currency": "EUR"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "RESERVATION_FAILED"
    assert "Insufficient funds" in data["message"]


@patch("main.process_payment_for_reservation")
def test_create_reservation_service_unavailable(mock_payment):
    """Test reservation creation when payment service is unavailable."""
    # Mock service unavailable
    from payment_client import PaymentServiceError

    mock_payment.side_effect = PaymentServiceError("Service unavailable")

    response = client.post(
        "/reservations", json={"user_id": "USER-003", "amount": 50.0, "currency": "EUR"}
    )

    assert response.status_code == 503
    assert "temporarily unavailable" in response.json()["detail"]["message"]


def test_get_reservation_not_found():
    """Test getting a non-existent reservation."""
    response = client.get("/reservations/RES-999999")

    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


@patch("main.process_payment_for_reservation")
def test_get_reservation_success(mock_payment):
    """Test getting an existing reservation."""
    # Create a reservation first
    mock_payment.return_value = (True, "TXN-456", "Payment successful")

    create_response = client.post(
        "/reservations", json={"user_id": "USER-004", "amount": 75.0, "currency": "EUR"}
    )

    reservation_id = create_response.json()["reservation_id"]

    # Get the reservation
    get_response = client.get(f"/reservations/{reservation_id}")

    assert get_response.status_code == 200
    data = get_response.json()
    assert data["reservation_id"] == reservation_id
    assert data["status"] == "RESERVATION_CONFIRMED"
    assert data["transaction_id"] == "TXN-456"
