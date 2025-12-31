"""
Event Store Implementation

Implements CQRS/Event Sourcing patterns:
- Event publishing and storage
- Event replay for aggregate reconstruction
- Projection updates for read models
"""

import logging
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from models import EventModel, EventType, ReservationModel, ReservationStatus

logger = logging.getLogger(__name__)


class EventStore:
    """
    Event store for managing domain events.

    Provides methods to:
    - Append events to the store
    - Retrieve events for an aggregate
    - Replay events to reconstruct state
    """

    def __init__(self, session: Session):
        """
        Initialize event store with a database session.

        Args:
            session: SQLAlchemy database session
        """
        self.session = session

    def append(
        self,
        aggregate_id: UUID,
        event_type: EventType,
        data: dict[str, Any],
        tenant_id: UUID,
        event_metadata: dict[str, Any] | None = None,
    ) -> EventModel:
        """
        Append a new event to the store.

        Args:
            aggregate_id: ID of the aggregate (reservation)
            event_type: Type of event
            data: Event payload
            tenant_id: Tenant ID for multitenancy
            event_metadata: Optional metadata (user info, correlation ID, etc.)

        Returns:
            The created event
        """
        # Get the next version for this aggregate
        version = self._get_next_version(aggregate_id)

        event = EventModel(
            id=uuid4(),
            aggregate_id=aggregate_id,
            aggregate_type="Reservation",
            event_type=event_type.value,
            version=version,
            data=data,
            event_metadata=event_metadata,
            tenant_id=tenant_id,
            created_at=datetime.utcnow(),
        )

        self.session.add(event)
        logger.info(
            f"Event appended: {event_type.value} for aggregate {aggregate_id} "
            f"(version {version})"
        )

        return event

    def get_events(
        self,
        aggregate_id: UUID,
        from_version: int | None = None,
    ) -> list[EventModel]:
        """
        Get all events for an aggregate.

        Args:
            aggregate_id: ID of the aggregate
            from_version: Optional starting version (for partial replay)

        Returns:
            List of events ordered by version
        """
        query = (
            select(EventModel)
            .where(EventModel.aggregate_id == aggregate_id)
            .order_by(EventModel.version)
        )

        if from_version is not None:
            query = query.where(EventModel.version >= from_version)

        return list(self.session.execute(query).scalars().all())

    def get_events_by_type(
        self,
        event_type: EventType,
        tenant_id: UUID | None = None,
        limit: int = 100,
    ) -> list[EventModel]:
        """
        Get events by type, optionally filtered by tenant.

        Args:
            event_type: Type of events to retrieve
            tenant_id: Optional tenant filter
            limit: Maximum number of events to return

        Returns:
            List of events
        """
        query = (
            select(EventModel)
            .where(EventModel.event_type == event_type.value)
            .order_by(EventModel.created_at.desc())
            .limit(limit)
        )

        if tenant_id is not None:
            query = query.where(EventModel.tenant_id == tenant_id)

        return list(self.session.execute(query).scalars().all())

    def _get_next_version(self, aggregate_id: UUID) -> int:
        """
        Get the next version number for an aggregate.

        Args:
            aggregate_id: ID of the aggregate

        Returns:
            Next version number
        """
        result = self.session.execute(
            select(EventModel.version)
            .where(EventModel.aggregate_id == aggregate_id)
            .order_by(EventModel.version.desc())
            .limit(1)
        ).scalar_one_or_none()

        return (result or 0) + 1


class ReservationAggregate:
    """
    Aggregate root for reservations.

    Encapsulates business logic and event generation
    for reservation operations.
    """

    def __init__(
        self,
        id: UUID,
        tenant_id: UUID,
        user_id: UUID,
        parking_spot_id: str,
        start_time: datetime,
        duration_hours: int,
        total_cost: float,
    ):
        """Initialize a new reservation aggregate."""
        self.id = id
        self.tenant_id = tenant_id
        self.user_id = user_id
        self.parking_spot_id = parking_spot_id
        self.start_time = start_time
        self.end_time = start_time + timedelta(hours=duration_hours)
        self.duration_hours = duration_hours
        self.total_cost = total_cost
        self.status = ReservationStatus.PENDING
        self.transaction_id: UUID | None = None
        self.created_at = datetime.utcnow()
        self.updated_at = self.created_at

    def to_event_data(self) -> dict[str, Any]:
        """Convert aggregate state to event data."""
        return {
            "id": str(self.id),
            "tenant_id": str(self.tenant_id),
            "user_id": str(self.user_id),
            "parking_spot_id": self.parking_spot_id,
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat(),
            "duration_hours": self.duration_hours,
            "total_cost": self.total_cost,
            "status": self.status.value,
            "transaction_id": str(self.transaction_id) if self.transaction_id else None,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }


class ReservationProjector:
    """
    Projector for updating reservation read model.

    Processes events and updates the materialized view (reservations table).
    """

    def __init__(self, session: Session):
        """
        Initialize projector with a database session.

        Args:
            session: SQLAlchemy database session
        """
        self.session = session

    def apply_event(self, event: EventModel) -> ReservationModel | None:
        """
        Apply an event to update the read model.

        Args:
            event: The event to apply

        Returns:
            The updated reservation model, or None if not applicable
        """
        event_type = EventType(event.event_type)
        handlers = {
            EventType.RESERVATION_CREATED: self._handle_reservation_created,
            EventType.RESERVATION_CONFIRMED: self._handle_status_change,
            EventType.RESERVATION_CANCELLED: self._handle_status_change,
            EventType.RESERVATION_COMPLETED: self._handle_status_change,
            EventType.RESERVATION_EXPIRED: self._handle_status_change,
            EventType.PAYMENT_PROCESSED: self._handle_payment_processed,
            EventType.PAYMENT_FAILED: self._handle_payment_failed,
        }

        handler = handlers.get(event_type)
        if handler:
            return handler(event)

        logger.warning(f"No handler for event type: {event_type}")
        return None

    def _handle_reservation_created(self, event: EventModel) -> ReservationModel:
        """Handle RESERVATION_CREATED event."""
        data = event.data

        reservation = ReservationModel(
            id=UUID(data["id"]),
            tenant_id=UUID(data["tenant_id"]),
            user_id=UUID(data["user_id"]),
            parking_spot_id=data["parking_spot_id"],
            start_time=datetime.fromisoformat(data["start_time"]),
            end_time=datetime.fromisoformat(data["end_time"]),
            duration_hours=data["duration_hours"],
            total_cost=data["total_cost"],
            status=data["status"],
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
        )

        self.session.add(reservation)
        logger.info(f"Reservation created: {reservation.id}")
        return reservation

    def _handle_status_change(self, event: EventModel) -> ReservationModel | None:
        """Handle status change events."""
        data = event.data
        reservation_id = UUID(data["id"])

        reservation = self.session.get(ReservationModel, reservation_id)
        if not reservation:
            logger.warning(f"Reservation not found: {reservation_id}")
            return None

        reservation.status = data["status"]
        reservation.updated_at = datetime.utcnow()
        logger.info(f"Reservation {reservation_id} status changed to {data['status']}")
        return reservation

    def _handle_payment_processed(self, event: EventModel) -> ReservationModel | None:
        """Handle PAYMENT_PROCESSED event."""
        data = event.data
        reservation_id = UUID(data["id"])

        reservation = self.session.get(ReservationModel, reservation_id)
        if not reservation:
            logger.warning(f"Reservation not found: {reservation_id}")
            return None

        reservation.status = ReservationStatus.CONFIRMED.value
        reservation.transaction_id = (
            str(data["transaction_id"]) if data.get("transaction_id") else None
        )
        reservation.updated_at = datetime.utcnow()
        logger.info(f"Payment processed for reservation {reservation_id}")
        return reservation

    def _handle_payment_failed(self, event: EventModel) -> ReservationModel | None:
        """Handle PAYMENT_FAILED event."""
        data = event.data
        reservation_id = UUID(data["id"])

        reservation = self.session.get(ReservationModel, reservation_id)
        if not reservation:
            logger.warning(f"Reservation not found: {reservation_id}")
            return None

        reservation.status = ReservationStatus.CANCELLED.value
        reservation.updated_at = datetime.utcnow()
        logger.info(f"Payment failed for reservation {reservation_id}")
        return reservation

    def rebuild_from_events(self, tenant_id: UUID | None = None) -> int:
        """
        Rebuild the read model from all events.

        This is useful for recovering from data corruption
        or when changing the projection logic.

        Args:
            tenant_id: Optional tenant filter

        Returns:
            Number of events processed
        """
        logger.info("Starting read model rebuild...")

        # Get all events ordered by creation time
        query = select(EventModel).order_by(EventModel.created_at)
        if tenant_id:
            query = query.where(EventModel.tenant_id == tenant_id)

        events = self.session.execute(query).scalars().all()

        # Clear existing read model
        if tenant_id:
            self.session.query(ReservationModel).filter(
                ReservationModel.tenant_id == tenant_id
            ).delete()
        else:
            self.session.query(ReservationModel).delete()

        # Replay all events
        count = 0
        for event in events:
            self.apply_event(event)
            count += 1

        logger.info(f"Read model rebuild complete: {count} events processed")
        return count
