"""
Reservation Service Models

Defines SQLAlchemy models for:
- ReservationModel: Read model (materialized view) for reservations
- EventModel: Event store for CQRS/Event Sourcing pattern

Supports multitenancy via tenant_id column with PostgreSQL RLS.
"""

import json
from datetime import datetime
from enum import Enum
from typing import Any
from uuid import uuid4

from sqlalchemy import DateTime, Float, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Base class for all models."""

    pass


class ReservationStatus(str, Enum):
    """Enum for reservation status."""

    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"
    EXPIRED = "EXPIRED"


class EventType(str, Enum):
    """Enum for event types in Event Sourcing."""

    RESERVATION_CREATED = "RESERVATION_CREATED"
    RESERVATION_CONFIRMED = "RESERVATION_CONFIRMED"
    RESERVATION_CANCELLED = "RESERVATION_CANCELLED"
    RESERVATION_COMPLETED = "RESERVATION_COMPLETED"
    RESERVATION_EXPIRED = "RESERVATION_EXPIRED"
    PAYMENT_PROCESSED = "PAYMENT_PROCESSED"
    PAYMENT_FAILED = "PAYMENT_FAILED"


class ReservationModel(Base):
    """
    Read model for reservations (materialized view).

    This is the denormalized read model in CQRS pattern.
    It's updated by projecting events from the event store.
    Supports multitenancy via tenant_id column.
    """

    __tablename__ = "reservations"

    # Primary key
    id: Mapped[str] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )

    # Multitenancy support
    tenant_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
    )

    # User reference (from user-service)
    user_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
    )

    # Parking spot reference (from parking-service)
    parking_spot_id: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        index=True,
    )

    # Reservation details
    start_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    end_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    duration_hours: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
    total_cost: Mapped[float] = mapped_column(
        Float,
        nullable=False,
    )

    # Status
    status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default=ReservationStatus.PENDING.value,
    )

    # Payment reference
    transaction_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
    )

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=datetime.utcnow,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    # Composite indexes for common queries
    __table_args__ = (
        Index("idx_reservations_tenant_user", "tenant_id", "user_id"),
        Index("idx_reservations_tenant_status", "tenant_id", "status"),
        Index(
            "idx_reservations_parking_time", "parking_spot_id", "start_time", "end_time"
        ),
    )


class EventModel(Base):
    """
    Event store for CQRS/Event Sourcing pattern.

    Stores all domain events as immutable records.
    Events are never updated or deleted, only appended.
    """

    __tablename__ = "event_store"

    # Event ID
    id: Mapped[str] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )

    # Aggregate ID (reservation ID)
    aggregate_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
    )

    # Aggregate type (for future extensibility)
    aggregate_type: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        default="Reservation",
    )

    # Event type
    event_type: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        index=True,
    )

    # Event version (for optimistic concurrency)
    version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
    )

    # Event data (JSON payload)
    data: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
    )

    # Event metadata (user info, correlation ID, etc.)
    event_metadata: Mapped[dict[str, Any] | None] = mapped_column(
        JSON,
        nullable=True,
    )

    # Tenant ID for multitenancy
    tenant_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
    )

    # Timestamp
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=datetime.utcnow,
    )

    # Composite indexes
    __table_args__ = (
        Index("idx_events_aggregate_version", "aggregate_id", "version"),
        Index("idx_events_tenant_type", "tenant_id", "event_type"),
        Index("idx_events_created_at", "created_at"),
    )

    def to_dict(self) -> dict[str, Any]:
        """Convert event to dictionary."""
        return {
            "id": str(self.id),
            "aggregate_id": str(self.aggregate_id),
            "aggregate_type": self.aggregate_type,
            "event_type": self.event_type,
            "version": self.version,
            "data": self.data,
            "event_metadata": self.event_metadata,
            "tenant_id": str(self.tenant_id),
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
