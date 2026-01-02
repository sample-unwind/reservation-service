# Reservation Service

Python/FastAPI microservice for handling parking reservations with CQRS/Event Sourcing architecture.

## Table of Contents

- [Architecture](#architecture)
  - [CQRS Pattern](#cqrs-pattern)
  - [Event Sourcing](#event-sourcing)
  - [Multitenancy](#multitenancy)
- [Event Sourcing Implementation](#event-sourcing-implementation)
  - [Core Concepts](#core-concepts)
  - [Event Types](#event-types)
  - [Event Store](#event-store)
  - [Projections](#projections)
  - [Aggregate Reconstruction](#aggregate-reconstruction)
  - [Read Model Rebuild](#read-model-rebuild)
- [API Reference](#api-reference)
  - [REST Endpoints](#rest-endpoints)
  - [GraphQL API](#graphql-api)
  - [Admin Endpoints](#admin-endpoints)
- [Local Development](#local-development)
- [Database Schema](#database-schema)
- [Testing](#testing)

## Architecture

### CQRS Pattern

This service implements **Command Query Responsibility Segregation (CQRS)**, which separates read and write operations:

```
                    ┌─────────────────────────────────────────────────────────┐
                    │                   CQRS Architecture                      │
                    └─────────────────────────────────────────────────────────┘

    ┌─────────────────────────────────┐     ┌─────────────────────────────────┐
    │         COMMAND SIDE            │     │          QUERY SIDE             │
    │         (Write Model)           │     │         (Read Model)            │
    └─────────────────────────────────┘     └─────────────────────────────────┘
                    │                                       │
                    ▼                                       ▼
    ┌─────────────────────────────────┐     ┌─────────────────────────────────┐
    │   GraphQL Mutations             │     │   GraphQL Queries               │
    │   - createReservation           │     │   - reservations                │
    │   - confirmReservation          │     │   - reservationById             │
    │   - cancelReservation           │     │   - reservationsByUser          │
    │   - completeReservation         │     │   - checkAvailability           │
    │   - payReservation              │     │   - reservationStats            │
    └─────────────────────────────────┘     └─────────────────────────────────┘
                    │                                       ▲
                    ▼                                       │
    ┌─────────────────────────────────┐                     │
    │       Event Store               │─────────────────────┤
    │   (Append-Only Event Log)       │     Projection      │
    │                                 │─────────────────────┘
    │   - RESERVATION_CREATED         │
    │   - PAYMENT_PROCESSED           │     ┌─────────────────────────────────┐
    │   - RESERVATION_CANCELLED       │     │   Reservations Table            │
    │   - RESERVATION_COMPLETED       │────▶│   (Materialized View)           │
    │   - etc.                        │     │   - Denormalized for queries    │
    └─────────────────────────────────┘     │   - Fast reads                  │
                                            └─────────────────────────────────┘
```

**Benefits of CQRS:**
- **Scalability**: Read and write models can be scaled independently
- **Flexibility**: Query model can be optimized for specific query patterns
- **Simplicity**: Each side has a focused responsibility
- **Auditability**: Complete history of all changes via events

### Event Sourcing

Instead of storing just the current state, we store all state changes as events:

```
Traditional Approach:              Event Sourcing Approach:
──────────────────────             ─────────────────────────

┌───────────────────┐              ┌───────────────────────────────────┐
│ reservations      │              │ event_store                       │
├───────────────────┤              ├───────────────────────────────────┤
│ id: uuid-1        │              │ Event 1: RESERVATION_CREATED      │
│ status: CONFIRMED │              │   data: {id: uuid-1, user: ...}   │
│ user_id: user-1   │              ├───────────────────────────────────┤
│ ...               │              │ Event 2: PAYMENT_PROCESSED        │
└───────────────────┘              │   data: {id: uuid-1, txn: ...}    │
     ▲                             ├───────────────────────────────────┤
     │                             │ Event 3: RESERVATION_COMPLETED    │
  Only current                     │   data: {id: uuid-1}              │
  state visible                    └───────────────────────────────────┘
                                        ▲
                                        │
                                   Complete history
                                   preserved forever
```

**Benefits of Event Sourcing:**
- **Complete Audit Trail**: Every change is recorded with timestamp and metadata
- **Time Travel**: Reconstruct state at any point in time
- **Debugging**: Replay events to understand what happened
- **Recovery**: Rebuild read model if corrupted
- **Analytics**: Mine historical data for insights

### Multitenancy

Row-Level Security (RLS) is implemented via `tenant_id` column:

- Tenant ID is extracted from `X-Tenant-ID` header
- PostgreSQL RLS policies enforce data isolation at database level
- RLS applies to all CRUD operations (SELECT, INSERT, UPDATE, DELETE)
- Application sets `app.tenant_id` session variable before each request
- Defense in depth: Database enforces isolation even if application has bugs

## Event Sourcing Implementation

### Core Concepts

| Concept | Description | Implementation |
|---------|-------------|----------------|
| **Event** | Immutable record of something that happened | `EventModel` in `models.py` |
| **Event Store** | Append-only storage for events | `event_store` table, `EventStore` class |
| **Aggregate** | Domain object that generates events | `ReservationAggregate` class |
| **Projector** | Applies events to update read model | `ReservationProjector` class |
| **Read Model** | Denormalized view optimized for queries | `reservations` table |

### Event Types

| Event Type | Description | Trigger |
|------------|-------------|---------|
| `RESERVATION_CREATED` | New reservation created | `createReservation` mutation |
| `RESERVATION_CONFIRMED` | Reservation confirmed manually | `confirmReservation` mutation |
| `RESERVATION_CANCELLED` | Reservation cancelled | `cancelReservation` mutation |
| `RESERVATION_COMPLETED` | Parking session ended | `completeReservation` mutation |
| `RESERVATION_EXPIRED` | Reservation expired (automatic) | Scheduled job (planned) |
| `PAYMENT_PROCESSED` | Payment succeeded | `payReservation` mutation |
| `PAYMENT_FAILED` | Payment failed | gRPC response from payment-service |

### Event Store

The event store is the source of truth. Events are:
- **Immutable**: Never updated or deleted
- **Ordered**: Each aggregate has versioned events
- **Complete**: Contains all data needed to reconstruct state

```python
# Appending an event
event_store = EventStore(db)
event = event_store.append(
    aggregate_id=reservation_id,
    event_type=EventType.RESERVATION_CREATED,
    data=aggregate.to_event_data(),
    tenant_id=tenant_id,
    event_metadata={"source": "graphql_mutation", "user": user_id}
)

# Retrieving events for an aggregate
events = event_store.get_events(reservation_id)

# Get events from a specific version (for partial replay)
events = event_store.get_events(reservation_id, from_version=5)
```

### Projections

Events are projected to the read model for efficient querying:

```python
# Projector applies events to update read model
projector = ReservationProjector(db)

# Apply a single event
reservation = projector.apply_event(event)

# Rebuild entire read model from events
events_processed = projector.rebuild_from_events(tenant_id)
```

### Aggregate Reconstruction

Aggregates can be reconstructed from their event history:

```python
# Load aggregate state by replaying all its events
event_store = EventStore(db)
aggregate = event_store.load_aggregate(reservation_id)

if aggregate:
    print(f"Status: {aggregate.status}")
    print(f"Last updated: {aggregate.updated_at}")
```

This is useful for:
- Validating business rules against current state
- Debugging issues by replaying events
- Testing event sourcing logic

### Read Model Rebuild

If the read model becomes corrupted or the projection logic changes:

```bash
# Via REST API
curl -X POST https://parkora.crn.si/api/v1/reservation/admin/rebuild \
  -H "X-Tenant-ID: 00000000-0000-0000-0000-000000000001"

# Response
{
  "success": true,
  "events_processed": 150,
  "message": "Successfully rebuilt read model from 150 events"
}
```

## API Reference

### REST Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health/live` | GET | Liveness probe for Kubernetes |
| `/health/ready` | GET | Readiness probe (includes DB check) |
| `/` | GET | API info and feature list |
| `/stats` | GET | Reservation statistics |
| `/docs` | GET | OpenAPI/Swagger documentation |
| `/redoc` | GET | ReDoc documentation |

### Admin Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/admin/events/stats` | GET | Event store statistics |
| `/admin/rebuild` | POST | Rebuild read model from events |

### GraphQL API

Available at `/graphql` with GraphiQL playground.

#### Queries

```graphql
# List reservations with pagination and filtering
query {
  reservations(limit: 10, offset: 0, status: "CONFIRMED") {
    id
    userId
    parkingSpotId
    startTime
    endTime
    status
    totalCost
  }
}

# Get single reservation
query {
  reservationById(id: "uuid-here") {
    id
    status
    transactionId
  }
}

# Check availability
query {
  checkAvailability(
    parkingSpotId: "parking-1"
    startTime: "2024-01-15T10:00:00Z"
    durationHours: 2
  ) {
    available
    conflicts
  }
}

# Get events for a reservation (audit trail)
query {
  eventsByReservation(reservationId: "uuid-here") {
    id
    eventType
    version
    data
    createdAt
  }
}

# Reservation statistics
query {
  reservationStats {
    totalReservations
    activeReservations
    completedReservations
    cancelledReservations
  }
}
```

#### Mutations

```graphql
# Create reservation
mutation {
  createReservation(input: {
    userId: "user-uuid"
    parkingSpotId: "parking-1"
    startTime: "2024-01-15T10:00:00Z"
    durationHours: 2
    totalCost: 5.00
  }) {
    id
    status
  }
}

# Process payment (calls payment-service via gRPC)
mutation {
  payReservation(id: "reservation-uuid") {
    success
    transactionId
    message
  }
}

# Cancel reservation
mutation {
  cancelReservation(id: "reservation-uuid", reason: "User cancelled") {
    id
    status
  }
}

# Complete reservation
mutation {
  completeReservation(id: "reservation-uuid") {
    id
    status
  }
}
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
| `DATABASE_URL` | PostgreSQL connection string | Required |
| `KEYCLOAK_URL` | Keycloak server URL | `https://keycloak.parkora.crn.si/auth/` |
| `KEYCLOAK_REALM` | Keycloak realm name | `parkora` |
| `KEYCLOAK_CLIENT_ID` | Client ID for token validation | `backend-services` |
| `PARKING_SERVICE_URL` | URL of parking-service | `http://parking-service` |
| `PAYMENT_SERVICE_URL` | URL of payment-service (gRPC) | `payment-service:50051` |

## Database Schema

### event_store (Write Model)

Immutable event log for Event Sourcing:

```sql
CREATE TABLE event_store (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    aggregate_id UUID NOT NULL,           -- Reservation ID
    aggregate_type VARCHAR(100) NOT NULL, -- 'Reservation'
    event_type VARCHAR(100) NOT NULL,     -- Event type enum
    version INTEGER NOT NULL,             -- Optimistic concurrency
    data JSONB NOT NULL,                  -- Event payload
    event_metadata JSONB,                 -- User info, correlation ID
    tenant_id UUID NOT NULL,              -- Multitenancy
    created_at TIMESTAMPTZ NOT NULL       -- Event timestamp
);

-- Key indexes
CREATE INDEX idx_events_aggregate_version ON event_store(aggregate_id, version);
CREATE INDEX idx_events_tenant_type ON event_store(tenant_id, event_type);
```

### reservations (Read Model)

Projected state for fast queries:

```sql
CREATE TABLE reservations (
    id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL,
    user_id UUID NOT NULL,
    parking_spot_id VARCHAR(255) NOT NULL,
    start_time TIMESTAMPTZ NOT NULL,
    end_time TIMESTAMPTZ NOT NULL,
    duration_hours INTEGER NOT NULL,
    total_cost DECIMAL(10, 2) NOT NULL,
    status VARCHAR(50) NOT NULL DEFAULT 'PENDING',
    transaction_id UUID,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);

-- Row-Level Security for multitenancy
ALTER TABLE reservations ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON reservations
    USING (tenant_id = current_setting('app.tenant_id')::UUID);
```

## Testing

```bash
# Activate virtual environment
source venv/bin/activate

# Run all tests
python -m pytest

# Run with coverage
python -m pytest --cov=. --cov-report=html

# Run specific test file
python -m pytest tests/test_event_store.py -v

# Run specific test class
python -m pytest tests/test_event_store.py::TestEventStore -v
```

### Test Categories

| Test File | Description |
|-----------|-------------|
| `tests/test_main.py` | Health endpoints, API basics |
| `tests/test_graphql.py` | GraphQL queries and mutations |
| `tests/test_event_store.py` | Event sourcing: store, projections, rebuild |

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

## Project Structure

```
reservation-service/
├── main.py              # FastAPI app, routes, middleware
├── schema.py            # GraphQL schema (Strawberry)
├── models.py            # SQLAlchemy models (Event, Reservation)
├── db.py                # Database connection, multitenancy
├── event_store.py       # CQRS/ES implementation
├── clients/
│   ├── parking_client.py   # HTTP client for parking-service
│   └── payment_client.py   # gRPC client for payment-service
├── tests/
│   ├── test_main.py        # Health endpoint tests
│   ├── test_graphql.py     # GraphQL tests
│   └── test_event_store.py # Event sourcing tests
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

| Service | Communication | Purpose |
|---------|---------------|---------|
| parking-service | HTTP | Provides parking spot data |
| payment-service | gRPC | Handles payment processing |
| notification-service | RabbitMQ | Sends reservation notifications |
| user-service | GraphQL | User authentication and profiles |
