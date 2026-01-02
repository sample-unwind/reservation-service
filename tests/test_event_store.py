"""
Test Event Store Implementation

Tests for CQRS/Event Sourcing functionality including:
- Aggregate creation and event data generation
- Event type validation

Note: Database-dependent tests require PostgreSQL and are skipped in CI.
The comprehensive integration tests run in the production-like environment.
"""

import uuid
from datetime import datetime, timedelta

import pytest

from event_store import ReservationAggregate
from models import EventType, ReservationStatus

# Test constants
TEST_TENANT_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
TEST_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000002")


class TestReservationAggregate:
    """Tests for ReservationAggregate class."""

    def test_create_aggregate(self):
        """Test creating a new aggregate."""
        aggregate_id = uuid.uuid4()
        start_time = datetime.utcnow() + timedelta(hours=1)

        aggregate = ReservationAggregate(
            id=aggregate_id,
            tenant_id=TEST_TENANT_ID,
            user_id=TEST_USER_ID,
            parking_spot_id="parking-1",
            start_time=start_time,
            duration_hours=2,
            total_cost=5.00,
        )

        assert aggregate.id == aggregate_id
        assert aggregate.tenant_id == TEST_TENANT_ID
        assert aggregate.user_id == TEST_USER_ID
        assert aggregate.parking_spot_id == "parking-1"
        assert aggregate.start_time == start_time
        assert aggregate.end_time == start_time + timedelta(hours=2)
        assert aggregate.duration_hours == 2
        assert aggregate.total_cost == 5.00
        assert aggregate.status == ReservationStatus.PENDING

    def test_to_event_data(self):
        """Test converting aggregate to event data."""
        aggregate_id = uuid.uuid4()
        start_time = datetime.utcnow() + timedelta(hours=1)

        aggregate = ReservationAggregate(
            id=aggregate_id,
            tenant_id=TEST_TENANT_ID,
            user_id=TEST_USER_ID,
            parking_spot_id="parking-1",
            start_time=start_time,
            duration_hours=2,
            total_cost=5.00,
        )

        data = aggregate.to_event_data()

        assert data["id"] == str(aggregate_id)
        assert data["tenant_id"] == str(TEST_TENANT_ID)
        assert data["user_id"] == str(TEST_USER_ID)
        assert data["parking_spot_id"] == "parking-1"
        assert data["duration_hours"] == 2
        assert data["total_cost"] == 5.00
        assert data["status"] == "PENDING"

    def test_aggregate_calculates_end_time(self):
        """Test that aggregate correctly calculates end time."""
        start_time = datetime(2024, 1, 15, 10, 0, 0)

        aggregate = ReservationAggregate(
            id=uuid.uuid4(),
            tenant_id=TEST_TENANT_ID,
            user_id=TEST_USER_ID,
            parking_spot_id="parking-1",
            start_time=start_time,
            duration_hours=3,
            total_cost=7.50,
        )

        expected_end = datetime(2024, 1, 15, 13, 0, 0)
        assert aggregate.end_time == expected_end

    def test_aggregate_initial_status_is_pending(self):
        """Test that new aggregates have PENDING status."""
        aggregate = ReservationAggregate(
            id=uuid.uuid4(),
            tenant_id=TEST_TENANT_ID,
            user_id=TEST_USER_ID,
            parking_spot_id="parking-1",
            start_time=datetime.utcnow(),
            duration_hours=1,
            total_cost=2.50,
        )

        assert aggregate.status == ReservationStatus.PENDING
        assert aggregate.transaction_id is None

    def test_aggregate_sets_timestamps(self):
        """Test that aggregate sets created_at and updated_at."""
        before = datetime.utcnow()

        aggregate = ReservationAggregate(
            id=uuid.uuid4(),
            tenant_id=TEST_TENANT_ID,
            user_id=TEST_USER_ID,
            parking_spot_id="parking-1",
            start_time=datetime.utcnow() + timedelta(hours=1),
            duration_hours=1,
            total_cost=2.50,
        )

        after = datetime.utcnow()

        assert before <= aggregate.created_at <= after
        assert aggregate.created_at == aggregate.updated_at


class TestEventTypes:
    """Tests for EventType enum."""

    def test_all_event_types_exist(self):
        """Test that all expected event types are defined."""
        expected_types = [
            "RESERVATION_CREATED",
            "RESERVATION_CONFIRMED",
            "RESERVATION_CANCELLED",
            "RESERVATION_COMPLETED",
            "RESERVATION_EXPIRED",
            "PAYMENT_PROCESSED",
            "PAYMENT_FAILED",
        ]

        for event_type in expected_types:
            assert hasattr(EventType, event_type)
            assert EventType[event_type].value == event_type

    def test_event_type_values(self):
        """Test event type string values."""
        assert EventType.RESERVATION_CREATED.value == "RESERVATION_CREATED"
        assert EventType.PAYMENT_PROCESSED.value == "PAYMENT_PROCESSED"
        assert EventType.RESERVATION_CANCELLED.value == "RESERVATION_CANCELLED"


class TestReservationStatus:
    """Tests for ReservationStatus enum."""

    def test_all_statuses_exist(self):
        """Test that all expected statuses are defined."""
        expected_statuses = [
            "PENDING",
            "CONFIRMED",
            "CANCELLED",
            "COMPLETED",
            "EXPIRED",
        ]

        for status in expected_statuses:
            assert hasattr(ReservationStatus, status)
            assert ReservationStatus[status].value == status

    def test_status_transitions(self):
        """Test valid status transition documentation."""
        # Document expected transitions for CQRS
        valid_transitions = {
            ReservationStatus.PENDING: [
                ReservationStatus.CONFIRMED,
                ReservationStatus.CANCELLED,
                ReservationStatus.EXPIRED,
            ],
            ReservationStatus.CONFIRMED: [
                ReservationStatus.COMPLETED,
                ReservationStatus.CANCELLED,
            ],
            ReservationStatus.COMPLETED: [],  # Final state
            ReservationStatus.CANCELLED: [],  # Final state
            ReservationStatus.EXPIRED: [],  # Final state
        }

        # Verify all statuses have defined transitions
        for status in ReservationStatus:
            assert status in valid_transitions
