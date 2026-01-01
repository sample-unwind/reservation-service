-- =============================================================================
-- Reservation Service Database Schema
-- =============================================================================
-- This script initializes the database schema for the reservation service.
-- It includes tables for Event Sourcing (event_store) and the read model (reservations).
-- Supports multitenancy via tenant_id column with PostgreSQL RLS.

-- Enable UUID extension
CREATE EXTENSION IF NOT EXISTS "pgcrypto";
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- =============================================================================
-- Enum Types
-- =============================================================================

-- Reservation status enum
DO $$ BEGIN
    CREATE TYPE reservation_status AS ENUM (
        'PENDING',
        'CONFIRMED',
        'CANCELLED',
        'COMPLETED',
        'EXPIRED'
    );
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;

-- Event type enum
DO $$ BEGIN
    CREATE TYPE event_type AS ENUM (
        'RESERVATION_CREATED',
        'RESERVATION_CONFIRMED',
        'RESERVATION_CANCELLED',
        'RESERVATION_COMPLETED',
        'RESERVATION_EXPIRED',
        'PAYMENT_PROCESSED',
        'PAYMENT_FAILED'
    );
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;

-- =============================================================================
-- Event Store Table (Write Model)
-- =============================================================================
-- Stores all domain events as immutable records for Event Sourcing pattern.
-- Events are never updated or deleted, only appended.

CREATE TABLE IF NOT EXISTS event_store (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    aggregate_id UUID NOT NULL,
    aggregate_type VARCHAR(100) NOT NULL DEFAULT 'Reservation',
    event_type VARCHAR(100) NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    data JSONB NOT NULL,
    event_metadata JSONB,
    tenant_id UUID NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexes for event_store
CREATE INDEX IF NOT EXISTS idx_events_aggregate_id ON event_store(aggregate_id);
CREATE INDEX IF NOT EXISTS idx_events_aggregate_version ON event_store(aggregate_id, version);
CREATE INDEX IF NOT EXISTS idx_events_event_type ON event_store(event_type);
CREATE INDEX IF NOT EXISTS idx_events_tenant_id ON event_store(tenant_id);
CREATE INDEX IF NOT EXISTS idx_events_tenant_type ON event_store(tenant_id, event_type);
CREATE INDEX IF NOT EXISTS idx_events_created_at ON event_store(created_at);

-- =============================================================================
-- Reservations Table (Read Model)
-- =============================================================================
-- Materialized view of reservation state, updated by projecting events.
-- This is the denormalized read model in CQRS pattern.

CREATE TABLE IF NOT EXISTS reservations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    user_id UUID NOT NULL,
    parking_spot_id VARCHAR(255) NOT NULL,
    start_time TIMESTAMPTZ NOT NULL,
    end_time TIMESTAMPTZ NOT NULL,
    duration_hours INTEGER NOT NULL,
    total_cost DECIMAL(10, 2) NOT NULL,
    status VARCHAR(50) NOT NULL DEFAULT 'PENDING',
    transaction_id UUID,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexes for reservations
CREATE INDEX IF NOT EXISTS idx_reservations_tenant_id ON reservations(tenant_id);
CREATE INDEX IF NOT EXISTS idx_reservations_user_id ON reservations(user_id);
CREATE INDEX IF NOT EXISTS idx_reservations_parking_spot_id ON reservations(parking_spot_id);
CREATE INDEX IF NOT EXISTS idx_reservations_status ON reservations(status);
CREATE INDEX IF NOT EXISTS idx_reservations_tenant_user ON reservations(tenant_id, user_id);
CREATE INDEX IF NOT EXISTS idx_reservations_tenant_status ON reservations(tenant_id, status);
CREATE INDEX IF NOT EXISTS idx_reservations_parking_time ON reservations(parking_spot_id, start_time, end_time);
CREATE INDEX IF NOT EXISTS idx_reservations_start_time ON reservations(start_time);
CREATE INDEX IF NOT EXISTS idx_reservations_end_time ON reservations(end_time);

-- =============================================================================
-- Row-Level Security (RLS) for Multitenancy
-- =============================================================================
-- Ensures STRICT data isolation between tenants using PostgreSQL RLS policies.
-- The application MUST set app.tenant_id session variable before any queries.
--
-- STRICT POLICY: If app.tenant_id is not set or empty, NO rows are returned.
-- This prevents any data leakage if the application fails to set the tenant.
--
-- RLS policies enforce:
-- - SELECT: Only rows matching current tenant_id are visible (none if not set)
-- - INSERT: New rows must have tenant_id matching current tenant_id
-- - UPDATE: Can only update rows matching current tenant_id
-- - DELETE: Can only delete rows matching current tenant_id

-- Enable RLS on tables
ALTER TABLE reservations ENABLE ROW LEVEL SECURITY;
ALTER TABLE event_store ENABLE ROW LEVEL SECURITY;

-- Force RLS to apply even to table owner
ALTER TABLE reservations FORCE ROW LEVEL SECURITY;
ALTER TABLE event_store FORCE ROW LEVEL SECURITY;

-- Drop existing policies if they exist
DROP POLICY IF EXISTS tenant_isolation_policy ON reservations;
DROP POLICY IF EXISTS tenant_isolation_policy ON event_store;
DROP POLICY IF EXISTS tenant_insert_policy ON reservations;
DROP POLICY IF EXISTS tenant_insert_policy ON event_store;

-- =============================================================================
-- Reservations Table RLS Policies
-- =============================================================================

-- STRICT policy: If app.tenant_id is not set or empty, return NO rows
-- This ensures complete tenant isolation with no fallback
CREATE POLICY tenant_isolation_policy ON reservations
    FOR ALL
    USING (
        NULLIF(current_setting('app.tenant_id', true), '') IS NOT NULL
        AND tenant_id = current_setting('app.tenant_id', true)::UUID
    )
    WITH CHECK (
        NULLIF(current_setting('app.tenant_id', true), '') IS NOT NULL
        AND tenant_id = current_setting('app.tenant_id', true)::UUID
    );

-- =============================================================================
-- Event Store Table RLS Policies
-- =============================================================================

-- STRICT policy: If app.tenant_id is not set or empty, return NO rows
-- Events are append-only, but we enforce full isolation
CREATE POLICY tenant_isolation_policy ON event_store
    FOR ALL
    USING (
        NULLIF(current_setting('app.tenant_id', true), '') IS NOT NULL
        AND tenant_id = current_setting('app.tenant_id', true)::UUID
    )
    WITH CHECK (
        NULLIF(current_setting('app.tenant_id', true), '') IS NOT NULL
        AND tenant_id = current_setting('app.tenant_id', true)::UUID
    );

-- =============================================================================
-- Helper Functions
-- =============================================================================

-- Function to update updated_at timestamp
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Trigger to auto-update updated_at on reservations
DROP TRIGGER IF EXISTS update_reservations_updated_at ON reservations;
CREATE TRIGGER update_reservations_updated_at
    BEFORE UPDATE ON reservations
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- =============================================================================
-- Sample Data (Development Only)
-- =============================================================================
-- Uncomment the following to insert sample data for testing

-- Default tenant ID for development
-- INSERT INTO reservations (tenant_id, user_id, parking_spot_id, start_time, end_time, duration_hours, total_cost, status)
-- VALUES (
--     '00000000-0000-0000-0000-000000000001',
--     '00000000-0000-0000-0000-000000000002',
--     'parking-1',
--     NOW() + interval '1 hour',
--     NOW() + interval '3 hours',
--     2,
--     5.00,
--     'CONFIRMED'
-- );

-- =============================================================================
-- Permissions (if using separate roles)
-- =============================================================================
-- GRANT SELECT, INSERT, UPDATE, DELETE ON reservations TO reservation_service;
-- GRANT SELECT, INSERT ON event_store TO reservation_service;
-- GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO reservation_service;
