"""
GraphQL Schema for Reservation Service

Defines GraphQL types, queries, and mutations for reservation management.
Implements CQRS pattern with Event Sourcing.

Multitenancy:
- PostgreSQL RLS (Row-Level Security) handles tenant isolation for all queries
- The tenant_id is set in the database session by main.py before any operations
- Queries do NOT need explicit tenant_id WHERE clauses (RLS handles this)
- INSERTs still need tenant_id as RLS only filters, doesn't enforce INSERT values
"""

from datetime import datetime, timedelta
from typing import Any, cast
from uuid import UUID as PyUUID
from uuid import uuid4

import strawberry
from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from event_store import EventStore, ReservationAggregate, ReservationProjector
from models import EventModel, EventType, ReservationModel, ReservationStatus

# =============================================================================
# GraphQL Types
# =============================================================================


@strawberry.type
class Reservation:
    """GraphQL type for reservation."""

    id: str
    tenant_id: str
    user_id: str
    parking_spot_id: str
    start_time: str
    end_time: str
    duration_hours: int
    total_cost: float
    status: str
    transaction_id: str | None
    created_at: str
    updated_at: str


@strawberry.type
class Event:
    """GraphQL type for domain events."""

    id: str
    aggregate_id: str
    event_type: str
    version: int
    data: str  # JSON string
    created_at: str


@strawberry.type
class ReservationStats:
    """GraphQL type for reservation statistics."""

    total_reservations: int
    active_reservations: int
    completed_reservations: int
    cancelled_reservations: int


@strawberry.type
class DeleteResult:
    """GraphQL type for delete operation result."""

    success: bool
    message: str | None = None


@strawberry.type
class AvailabilityResult:
    """GraphQL type for availability check result."""

    available: bool
    conflicts: list[str] | None = None


# =============================================================================
# GraphQL Inputs
# =============================================================================


@strawberry.input
class CreateReservationInput:
    """Input for creating a new reservation."""

    user_id: str
    parking_spot_id: str
    start_time: str  # ISO 8601 format
    duration_hours: int
    total_cost: float


@strawberry.input
class UpdateReservationInput:
    """Input for updating an existing reservation."""

    id: str
    start_time: str | None = None
    duration_hours: int | None = None


# =============================================================================
# Helper Functions
# =============================================================================


def to_graphql_reservation(r: ReservationModel) -> Reservation:
    """Convert SQLAlchemy model to GraphQL type."""
    created_at = cast(datetime | None, r.created_at)
    updated_at = cast(datetime | None, r.updated_at)
    start_time = cast(datetime | None, r.start_time)
    end_time = cast(datetime | None, r.end_time)

    return Reservation(
        id=str(r.id),
        tenant_id=str(r.tenant_id),
        user_id=str(r.user_id),
        parking_spot_id=str(r.parking_spot_id),
        start_time=start_time.isoformat() if start_time else "",
        end_time=end_time.isoformat() if end_time else "",
        duration_hours=int(r.duration_hours),
        total_cost=float(r.total_cost),
        status=str(r.status),
        transaction_id=str(r.transaction_id) if r.transaction_id else None,
        created_at=created_at.isoformat() if created_at else "",
        updated_at=updated_at.isoformat() if updated_at else "",
    )


def to_graphql_event(e: EventModel) -> Event:
    """Convert SQLAlchemy event model to GraphQL type."""
    import json

    return Event(
        id=str(e.id),
        aggregate_id=str(e.aggregate_id),
        event_type=str(e.event_type),
        version=int(e.version),
        data=json.dumps(e.data),
        created_at=e.created_at.isoformat() if e.created_at else "",
    )


def get_tenant_id(info: strawberry.Info) -> PyUUID:
    """
    Extract tenant ID from request context.

    This is used primarily for:
    - INSERT operations (RLS doesn't enforce INSERT values)
    - Event store writes (need explicit tenant_id)
    - Validation purposes

    Note: For SELECT queries, PostgreSQL RLS handles filtering automatically
    based on the app.tenant_id session variable set by main.py.

    Falls back to a default tenant ID for development/testing.
    """
    tenant_id = info.context.get("tenant_id")
    if tenant_id:
        return PyUUID(tenant_id) if isinstance(tenant_id, str) else tenant_id

    # Default tenant ID for development
    return PyUUID("00000000-0000-0000-0000-000000000001")


# =============================================================================
# GraphQL Query
# =============================================================================


@strawberry.type
class Query:
    """GraphQL queries for reservation service."""

    @strawberry.field
    def reservations(
        self,
        info: strawberry.Info,
        status: str | None = None,
        user_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Reservation]:
        """
        Get all reservations with optional filtering.

        Tenant isolation is handled by PostgreSQL RLS automatically.

        Args:
            status: Filter by status (e.g., CONFIRMED, PENDING)
            user_id: Filter by user ID
            limit: Maximum number of results
            offset: Number of results to skip
        """
        db: Session = info.context["db"]

        # RLS handles tenant filtering - no need for explicit WHERE clause
        query = (
            select(ReservationModel)
            .order_by(ReservationModel.created_at.desc())
            .limit(limit)
            .offset(offset)
        )

        if status:
            query = query.where(ReservationModel.status == status)
        if user_id:
            query = query.where(ReservationModel.user_id == PyUUID(user_id))

        rows = db.execute(query).scalars().all()
        return [to_graphql_reservation(r) for r in rows]

    @strawberry.field
    def reservation_by_id(self, info: strawberry.Info, id: str) -> Reservation | None:
        """Get a single reservation by ID. RLS handles tenant isolation."""
        db: Session = info.context["db"]

        # RLS handles tenant filtering automatically
        row = db.execute(
            select(ReservationModel).where(ReservationModel.id == PyUUID(id))
        ).scalar_one_or_none()

        return to_graphql_reservation(row) if row else None

    @strawberry.field
    def reservations_by_user(
        self,
        info: strawberry.Info,
        user_id: str,
        include_completed: bool = False,
    ) -> list[Reservation]:
        """Get all reservations for a specific user. RLS handles tenant isolation."""
        db: Session = info.context["db"]

        # RLS handles tenant filtering automatically
        query = (
            select(ReservationModel)
            .where(ReservationModel.user_id == PyUUID(user_id))
            .order_by(ReservationModel.start_time.desc())
        )

        if not include_completed:
            query = query.where(
                ReservationModel.status.in_(
                    [
                        ReservationStatus.PENDING.value,
                        ReservationStatus.CONFIRMED.value,
                    ]
                )
            )

        rows = db.execute(query).scalars().all()
        return [to_graphql_reservation(r) for r in rows]

    @strawberry.field
    def reservations_by_parking_spot(
        self,
        info: strawberry.Info,
        parking_spot_id: str,
        start_time: str | None = None,
        end_time: str | None = None,
    ) -> list[Reservation]:
        """Get all reservations for a specific parking spot. RLS handles tenant isolation."""
        db: Session = info.context["db"]

        # RLS handles tenant filtering automatically
        query = (
            select(ReservationModel)
            .where(
                and_(
                    ReservationModel.parking_spot_id == parking_spot_id,
                    ReservationModel.status.in_(
                        [
                            ReservationStatus.PENDING.value,
                            ReservationStatus.CONFIRMED.value,
                        ]
                    ),
                )
            )
            .order_by(ReservationModel.start_time)
        )

        # Optional time range filter
        if start_time:
            start_dt = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
            query = query.where(ReservationModel.end_time >= start_dt)
        if end_time:
            end_dt = datetime.fromisoformat(end_time.replace("Z", "+00:00"))
            query = query.where(ReservationModel.start_time <= end_dt)

        rows = db.execute(query).scalars().all()
        return [to_graphql_reservation(r) for r in rows]

    @strawberry.field
    def check_availability(
        self,
        info: strawberry.Info,
        parking_spot_id: str,
        start_time: str,
        duration_hours: int,
    ) -> AvailabilityResult:
        """Check if a parking spot is available. RLS handles tenant isolation."""
        db: Session = info.context["db"]

        start_dt = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
        end_dt = start_dt + timedelta(hours=duration_hours)

        # RLS handles tenant filtering - find conflicting reservations
        conflicts = (
            db.execute(
                select(ReservationModel).where(
                    and_(
                        ReservationModel.parking_spot_id == parking_spot_id,
                        ReservationModel.status.in_(
                            [
                                ReservationStatus.PENDING.value,
                                ReservationStatus.CONFIRMED.value,
                            ]
                        ),
                        # Check for time overlap
                        ReservationModel.start_time < end_dt,
                        ReservationModel.end_time > start_dt,
                    )
                )
            )
            .scalars()
            .all()
        )

        if conflicts:
            conflict_ids = [str(c.id) for c in conflicts]
            return AvailabilityResult(available=False, conflicts=conflict_ids)

        return AvailabilityResult(available=True, conflicts=None)

    @strawberry.field
    def reservation_stats(self, info: strawberry.Info) -> ReservationStats:
        """Get reservation statistics. RLS handles tenant isolation."""
        db: Session = info.context["db"]

        # RLS handles tenant filtering - count by status
        total = db.query(ReservationModel).count()

        active = (
            db.query(ReservationModel)
            .filter(
                ReservationModel.status.in_(
                    [
                        ReservationStatus.PENDING.value,
                        ReservationStatus.CONFIRMED.value,
                    ]
                )
            )
            .count()
        )

        completed = (
            db.query(ReservationModel)
            .filter(ReservationModel.status == ReservationStatus.COMPLETED.value)
            .count()
        )

        cancelled = (
            db.query(ReservationModel)
            .filter(ReservationModel.status == ReservationStatus.CANCELLED.value)
            .count()
        )

        return ReservationStats(
            total_reservations=total,
            active_reservations=active,
            completed_reservations=completed,
            cancelled_reservations=cancelled,
        )

    @strawberry.field
    def events_by_reservation(
        self,
        info: strawberry.Info,
        reservation_id: str,
    ) -> list[Event]:
        """Get all events for a specific reservation (for debugging/audit).
        RLS handles tenant isolation for event_store table."""
        db: Session = info.context["db"]

        # RLS handles tenant filtering on event_store table
        event_store = EventStore(db)
        events = event_store.get_events(PyUUID(reservation_id))

        return [to_graphql_event(e) for e in events]


# =============================================================================
# GraphQL Mutation
# =============================================================================


@strawberry.type
class Mutation:
    """GraphQL mutations for reservation service."""

    @strawberry.mutation
    def create_reservation(
        self,
        info: strawberry.Info,
        input: CreateReservationInput,
    ) -> Reservation:
        """
        Create a new reservation.

        This mutation:
        1. Validates the input
        2. Checks availability (RLS handles tenant filtering)
        3. Creates an aggregate with explicit tenant_id
        4. Emits a RESERVATION_CREATED event
        5. Projects the event to the read model
        """
        db: Session = info.context["db"]
        # Need tenant_id for INSERT operations (RLS doesn't enforce INSERT values)
        tenant_id = get_tenant_id(info)

        # Parse input
        start_time = datetime.fromisoformat(input.start_time.replace("Z", "+00:00"))
        end_time = start_time + timedelta(hours=input.duration_hours)

        # Validate duration
        if input.duration_hours <= 0:
            raise ValueError("Duration must be positive")
        if input.duration_hours > 24:
            raise ValueError("Maximum reservation duration is 24 hours")

        # Validate cost
        if input.total_cost < 0:
            raise ValueError("Total cost cannot be negative")

        # Check availability - RLS handles tenant filtering
        conflicts = (
            db.execute(
                select(ReservationModel).where(
                    and_(
                        ReservationModel.parking_spot_id == input.parking_spot_id,
                        ReservationModel.status.in_(
                            [
                                ReservationStatus.PENDING.value,
                                ReservationStatus.CONFIRMED.value,
                            ]
                        ),
                        ReservationModel.start_time < end_time,
                        ReservationModel.end_time > start_time,
                    )
                )
            )
            .scalars()
            .all()
        )

        if conflicts:
            raise ValueError(
                f"Parking spot is not available for the requested time slot. "
                f"Conflicts with {len(conflicts)} existing reservation(s)."
            )

        # Create aggregate
        reservation_id = uuid4()
        aggregate = ReservationAggregate(
            id=reservation_id,
            tenant_id=tenant_id,
            user_id=PyUUID(input.user_id),
            parking_spot_id=input.parking_spot_id,
            start_time=start_time,
            duration_hours=input.duration_hours,
            total_cost=input.total_cost,
        )

        # Create event
        event_store = EventStore(db)
        event_metadata = {
            "user_id": input.user_id,
            "source": "graphql_mutation",
        }

        # Add user info from context if available
        current_user = info.context.get("current_user")
        if current_user:
            event_metadata["authenticated_user"] = current_user.get("sub")

        event = event_store.append(
            aggregate_id=reservation_id,
            event_type=EventType.RESERVATION_CREATED,
            data=aggregate.to_event_data(),
            tenant_id=tenant_id,
            event_metadata=event_metadata,
        )

        # Project event to read model
        projector = ReservationProjector(db)
        reservation = projector.apply_event(event)

        # Commit transaction
        db.commit()

        if not reservation:
            raise ValueError("Failed to create reservation")

        return to_graphql_reservation(reservation)

    @strawberry.mutation
    def confirm_reservation(
        self,
        info: strawberry.Info,
        id: str,
        transaction_id: str | None = None,
    ) -> Reservation:
        """
        Confirm a pending reservation after payment.
        RLS handles tenant isolation for the SELECT query.

        This mutation:
        1. Validates the reservation exists and is PENDING
        2. Emits a PAYMENT_PROCESSED event
        3. Updates the read model to CONFIRMED
        """
        db: Session = info.context["db"]
        # Need tenant_id for event store INSERT
        tenant_id = get_tenant_id(info)
        reservation_id = PyUUID(id)

        # Get existing reservation - RLS handles tenant filtering
        reservation = db.execute(
            select(ReservationModel).where(ReservationModel.id == reservation_id)
        ).scalar_one_or_none()

        if not reservation:
            raise ValueError("Reservation not found")

        if reservation.status != ReservationStatus.PENDING.value:
            raise ValueError(
                f"Cannot confirm reservation with status: {reservation.status}"
            )

        # Create event
        event_store = EventStore(db)
        event = event_store.append(
            aggregate_id=reservation_id,
            event_type=EventType.PAYMENT_PROCESSED,
            data={
                "id": str(reservation_id),
                "status": ReservationStatus.CONFIRMED.value,
                "transaction_id": transaction_id,
            },
            tenant_id=tenant_id,
            event_metadata={"source": "graphql_mutation"},
        )

        # Project event
        projector = ReservationProjector(db)
        projector.apply_event(event)

        db.commit()
        db.refresh(reservation)

        return to_graphql_reservation(reservation)

    @strawberry.mutation
    def cancel_reservation(
        self,
        info: strawberry.Info,
        id: str,
        reason: str | None = None,
    ) -> Reservation:
        """
        Cancel an existing reservation.
        RLS handles tenant isolation for SELECT and event INSERT.

        This mutation:
        1. Validates the reservation exists and is cancellable
        2. Emits a RESERVATION_CANCELLED event
        3. Updates the read model to CANCELLED
        """
        db: Session = info.context["db"]
        # Need tenant_id for event store INSERT (RLS enforces it matches)
        tenant_id = get_tenant_id(info)
        reservation_id = PyUUID(id)

        # Get existing reservation - RLS handles tenant filtering
        reservation = db.execute(
            select(ReservationModel).where(ReservationModel.id == reservation_id)
        ).scalar_one_or_none()

        if not reservation:
            raise ValueError("Reservation not found")

        if reservation.status not in [
            ReservationStatus.PENDING.value,
            ReservationStatus.CONFIRMED.value,
        ]:
            raise ValueError(
                f"Cannot cancel reservation with status: {reservation.status}"
            )

        # Create event
        event_store = EventStore(db)
        event = event_store.append(
            aggregate_id=reservation_id,
            event_type=EventType.RESERVATION_CANCELLED,
            data={
                "id": str(reservation_id),
                "status": ReservationStatus.CANCELLED.value,
                "reason": reason,
            },
            tenant_id=tenant_id,
            event_metadata={"source": "graphql_mutation"},
        )

        # Project event
        projector = ReservationProjector(db)
        projector.apply_event(event)

        db.commit()
        db.refresh(reservation)

        return to_graphql_reservation(reservation)

    @strawberry.mutation
    def complete_reservation(
        self,
        info: strawberry.Info,
        id: str,
    ) -> Reservation:
        """
        Mark a reservation as completed (after parking session ends).
        RLS handles tenant isolation for SELECT and event INSERT.
        """
        db: Session = info.context["db"]
        # Need tenant_id for event store INSERT (RLS enforces it matches)
        tenant_id = get_tenant_id(info)
        reservation_id = PyUUID(id)

        # Get existing reservation - RLS handles tenant filtering
        reservation = db.execute(
            select(ReservationModel).where(ReservationModel.id == reservation_id)
        ).scalar_one_or_none()

        if not reservation:
            raise ValueError("Reservation not found")

        if reservation.status != ReservationStatus.CONFIRMED.value:
            raise ValueError(
                f"Cannot complete reservation with status: {reservation.status}"
            )

        # Create event
        event_store = EventStore(db)
        event = event_store.append(
            aggregate_id=reservation_id,
            event_type=EventType.RESERVATION_COMPLETED,
            data={
                "id": str(reservation_id),
                "status": ReservationStatus.COMPLETED.value,
            },
            tenant_id=tenant_id,
            event_metadata={"source": "graphql_mutation"},
        )

        # Project event
        projector = ReservationProjector(db)
        projector.apply_event(event)

        db.commit()
        db.refresh(reservation)

        return to_graphql_reservation(reservation)

    @strawberry.mutation
    def delete_reservation(
        self,
        info: strawberry.Info,
        id: str,
    ) -> DeleteResult:
        """
        Delete a reservation (admin only, use with caution).
        RLS handles tenant isolation for SELECT and DELETE.

        Note: This is a hard delete. In production, prefer cancel_reservation.
        """
        db: Session = info.context["db"]

        # RLS handles tenant filtering for both SELECT and DELETE
        reservation = db.execute(
            select(ReservationModel).where(ReservationModel.id == PyUUID(id))
        ).scalar_one_or_none()

        if not reservation:
            return DeleteResult(success=False, message="Reservation not found")

        # Only allow deleting pending reservations
        if reservation.status not in [
            ReservationStatus.PENDING.value,
            ReservationStatus.CANCELLED.value,
        ]:
            return DeleteResult(
                success=False,
                message=f"Cannot delete reservation with status: {reservation.status}",
            )

        db.delete(reservation)
        db.commit()

        return DeleteResult(success=True, message="Reservation deleted")


# =============================================================================
# Schema
# =============================================================================

schema = strawberry.Schema(query=Query, mutation=Mutation)
