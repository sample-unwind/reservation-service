# Reservation Service

Python/FastAPI microservice for handling parking reservations with CQRS/Event Sourcing architecture.

## Architecture

### CQRS/Event Sourcing

This service implements the Command Query Responsibility Segregation (CQRS) pattern with Event Sourcing:

- **Event Store**: All state changes are stored as immutable events in the `event_store` table
- **Read Model**: A projected `reservations` table for fast queries, updated via event projections
- **Aggregates**: Business logic encapsulated in the `ReservationAggregate` class

### Multitenancy

Row-Level Security (RLS) is implemented via `tenant_id` column:
- Tenant ID is extracted from `X-Tenant-ID` header
- PostgreSQL RLS policies enforce data isolation

## Tech Stack

- **Framework**: FastAPI with async support
- **GraphQL**: Strawberry GraphQL
- **Database**: PostgreSQL with SQLAlchemy ORM
- **Authentication**: Keycloak (via python-keycloak)
- **External Services**: 
  - parking-service (HTTP)
  - payment-service (gRPC - planned)
  - notification-service (RabbitMQ - planned)

## API Endpoints

### REST

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health/live` | GET | Liveness probe |
| `/health/ready` | GET | Readiness probe |
| `/stats` | GET | Reservation statistics |
| `/docs` | GET | OpenAPI documentation |

### GraphQL

Available at `/graphql` with GraphiQL playground.

#### Queries

```graphql
# List reservations with pagination
reservations(limit: Int, offset: Int): [Reservation!]!

# Get reservation by ID
reservationById(id: ID!): Reservation

# Get reservations by user
reservationsByUser(userId: String!): [Reservation!]!

# Get reservations by parking spot
reservationsByParkingSpot(parkingSpotId: String!): [Reservation!]!

# Check parking spot availability
checkAvailability(parkingSpotId: String!, startTime: DateTime!, endTime: DateTime!): AvailabilityResult!

# Get reservation statistics
reservationStats: ReservationStats!

# Get events for a reservation (Event Sourcing)
eventsByReservation(reservationId: ID!): [Event!]!
```

#### Mutations

```graphql
# Create a new reservation
createReservation(input: CreateReservationInput!): CreateReservationResult!

# Confirm a pending reservation
confirmReservation(id: ID!): ReservationResult!

# Cancel a reservation
cancelReservation(id: ID!): ReservationResult!

# Complete a reservation
completeReservation(id: ID!): ReservationResult!

# Delete a reservation (soft delete)
deleteReservation(id: ID!): DeleteResult!
```

## Local Development

### Prerequisites

- Python 3.11+
- PostgreSQL 15+
- Docker & Docker Compose (optional)

### Setup

```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate  # Linux/Mac

# Install dependencies
pip install -r requirements.txt

# Copy environment template
cp .env.example .env
# Edit .env with your configuration

# Start PostgreSQL (via Docker)
docker-compose up -d postgres

# Run the service
uvicorn main:app --reload --port 8000
```

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `DATABASE_URL` | PostgreSQL connection string | `postgresql://...` |
| `KEYCLOAK_URL` | Keycloak server URL | - |
| `KEYCLOAK_REALM` | Keycloak realm name | `parkora` |
| `KEYCLOAK_CLIENT_ID` | Client ID for token validation | `backend-services` |
| `PARKING_SERVICE_URL` | URL of parking-service | `http://parking-service` |
| `PAYMENT_SERVICE_URL` | URL of payment-service (gRPC) | `payment-service:50051` |

## Testing

```bash
# Run tests
python -m pytest

# Run with coverage
python -m pytest --cov=. --cov-report=html
```

## Code Quality

```bash
# Format code
black .
isort .

# Lint
flake8 . --count --select=E9,F63,F7,F82 --show-source --statistics

# Type check
mypy . --ignore-missing-imports
```

## CI/CD

GitHub Actions workflow (`.github/workflows/ci-cd.yml`):

1. **Build & Test**: Lint, type check, run tests
2. **Build Image**: Multi-arch Docker image (amd64, arm64)
3. **Push**: GitHub Container Registry (`ghcr.io/sample-unwind/reservation-service`)

### Manual Deployment

```bash
# Get AKS credentials
az aks get-credentials --resource-group rg-parkora --name aks-parkora

# Deploy with Helm
helm upgrade --install reservation-service ./helm/reservation-service \
  --namespace parkora \
  --set image.tag=main
```

## Database Schema

### event_store

Immutable event log for Event Sourcing:

```sql
CREATE TABLE event_store (
    id UUID PRIMARY KEY,
    aggregate_id UUID NOT NULL,
    aggregate_type VARCHAR(50) NOT NULL,
    event_type VARCHAR(50) NOT NULL,
    event_data JSONB NOT NULL,
    metadata JSONB,
    version INTEGER NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

### reservations (Read Model)

Projected state for fast queries:

```sql
CREATE TABLE reservations (
    id UUID PRIMARY KEY,
    user_id VARCHAR(255) NOT NULL,
    parking_spot_id VARCHAR(255) NOT NULL,
    start_time TIMESTAMPTZ NOT NULL,
    end_time TIMESTAMPTZ NOT NULL,
    duration_hours INTEGER NOT NULL,
    total_cost DECIMAL(10,2) NOT NULL,
    status VARCHAR(20) NOT NULL,
    tenant_id VARCHAR(255),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
```

## Event Types

| Event | Description |
|-------|-------------|
| `RESERVATION_CREATED` | New reservation created |
| `RESERVATION_CONFIRMED` | Reservation confirmed |
| `RESERVATION_CANCELLED` | Reservation cancelled |
| `RESERVATION_COMPLETED` | Reservation completed |
| `RESERVATION_EXPIRED` | Reservation expired (automatic) |

## Project Structure

```
reservation-service/
├── main.py              # FastAPI app, routes, middleware
├── schema.py            # GraphQL schema (Strawberry)
├── models.py            # SQLAlchemy models
├── db.py                # Database connection, multitenancy
├── event_store.py       # CQRS/ES implementation
├── clients/
│   ├── parking_client.py   # HTTP client for parking-service
│   └── payment_client.py   # gRPC client for payment-service
├── tests/
│   ├── test_main.py        # Health endpoint tests
│   └── test_graphql.py     # GraphQL tests
├── db/init/
│   └── 001_init.sql        # Database schema
├── helm/reservation-service/
│   ├── Chart.yaml
│   ├── values.yaml
│   └── templates/
└── .github/workflows/
    └── ci-cd.yml
```

## Related Services

- **parking-service**: Provides parking spot data and availability
- **payment-service**: Handles payment processing (gRPC)
- **notification-service**: Sends reservation notifications (RabbitMQ)
- **user-service**: User authentication and profiles
