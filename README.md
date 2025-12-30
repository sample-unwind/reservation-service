# Reservation Service

## Description
Python/FastAPI microservice for handling reservations with CQRS/ES and gRPC integration for payment processing.

## Features
- **CQRS/Event Sourcing**: Track reservation state through events
- **gRPC Integration**: Synchronous communication with payment-service
- **Error Handling**: Retry logic and graceful degradation
- **Health Endpoints**: Kubernetes-ready liveness and readiness probes

## Setup
- Install Python 3.11
- Run `pip install -r requirements.txt`
- Set environment variables (optional):
  - `PAYMENT_SERVICE_HOST` (default: payment-service)
  - `PAYMENT_SERVICE_PORT` (default: 50051)
- Run `uvicorn main:app --reload`

## API Endpoints

### Health
- `GET /health/live` - Liveness probe
- `GET /health/ready` - Readiness probe

### Reservations
- `POST /reservations` - Create reservation and process payment
  ```json
  {
    "user_id": "USER-123",
    "amount": 100.0,
    "currency": "EUR"
  }
  ```
- `GET /reservations/{reservation_id}` - Get reservation details

## gRPC Integration

### Payment Service Communication
The service integrates with payment-service via gRPC for payment processing.

**Features:**
- 5-second timeout per request
- 3 retry attempts for transient failures
- Graceful degradation when payment service is unavailable

**Event Flow:**
1. `RESERVATION_CREATED` - Initial reservation
2. gRPC call to payment-service
3. `RESERVATION_CONFIRMED` - Payment successful
4. `RESERVATION_FAILED` - Payment failed or service unavailable

### Proto File
Proto definition located at `proto/payment.proto` (copied from payment-service).

To regenerate gRPC client code:
```bash
python -m grpc_tools.protoc -I./proto --python_out=. --grpc_python_out=. proto/payment.proto
```

## Testing
Run tests with:
```bash
python -m pytest -v
```

## CI/CD
This service uses GitHub Actions for CI/CD.

- **Triggers**: Push to main, PRs, releases
- **Linting**: black, mypy, isort, flake8
- **Testing**: pytest with comprehensive coverage
- **Build**: Docker multi-platform images (amd64, arm64)
- **Deploy**: Placeholders for ACR push and Helm upgrade on AKS

See `.github/workflows/ci-cd.yml` for details.

## Docker
Build and run:
```bash
docker build -t reservation-service .
docker run -p 8000:8000 \
  -e PAYMENT_SERVICE_HOST=payment-service \
  -e PAYMENT_SERVICE_PORT=50051 \
  reservation-service
```