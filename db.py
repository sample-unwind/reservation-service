"""
Database Configuration and Session Management

Provides SQLAlchemy engine, session management, and database utilities.
Implements multitenancy via PostgreSQL RLS (Row-Level Security).

RLS Implementation:
- Each request sets `app.tenant_id` session variable before queries
- PostgreSQL RLS policies filter data based on this variable
- This provides database-level tenant isolation (defense in depth)
"""

import logging
import os
from collections.abc import Generator
from contextlib import contextmanager
from typing import Any
from uuid import UUID

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from models import Base

# Set up logging
logger = logging.getLogger(__name__)

# Database URL from environment variable
DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL environment variable is required. "
        "Example: postgresql://user:password@localhost:5432/reservation_db"
    )

# Create engine with connection pooling
engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,  # Verify connections before use
    pool_size=5,  # Number of connections to keep
    max_overflow=10,  # Additional connections when pool is exhausted
    echo=os.getenv("SQL_DEBUG", "false").lower() == "true",  # SQL logging
)

# Session factory
SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
    expire_on_commit=False,  # Keep objects usable after commit
)


def get_db() -> Generator[Session, None, None]:
    """
    Dependency for FastAPI to get database session.

    Yields:
        Session: SQLAlchemy database session

    Usage:
        @app.get("/items")
        def get_items(db: Session = Depends(get_db)):
            return db.query(Item).all()
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def get_db_context() -> Generator[Session, None, None]:
    """
    Context manager for database session (for use outside FastAPI).

    Usage:
        with get_db_context() as db:
            db.query(Item).all()
    """
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def set_tenant_id(session: Session, tenant_id: str | UUID) -> None:
    """
    Set the current tenant ID for RLS (Row-Level Security).

    This sets a PostgreSQL session variable that RLS policies use
    to filter data by tenant. MUST be called before any queries
    in a multi-tenant context.

    For non-PostgreSQL databases (e.g., SQLite in tests), this is a no-op
    since those databases don't support RLS.

    Args:
        session: SQLAlchemy session
        tenant_id: UUID string or UUID object of the tenant

    Raises:
        ValueError: If tenant_id is invalid
    """
    if tenant_id is None:
        logger.warning("Attempted to set None tenant_id - skipping RLS setup")
        return

    # Convert UUID to string if needed
    tenant_id_str = str(tenant_id)

    # Validate UUID format to prevent SQL injection
    try:
        UUID(tenant_id_str)
    except (ValueError, TypeError) as e:
        logger.error(f"Invalid tenant_id format: {tenant_id_str}")
        raise ValueError(f"Invalid tenant_id format: {tenant_id_str}") from e

    # Only set RLS variable for PostgreSQL
    # SQLite and other databases don't support SET command or RLS
    try:
        session.execute(text(f"SET app.tenant_id = '{tenant_id_str}'"))
        logger.debug(f"RLS tenant_id set to: {tenant_id_str}")
    except Exception as e:
        # Non-PostgreSQL databases will fail - that's OK for testing
        logger.debug(f"Could not set RLS tenant_id (non-PostgreSQL?): {e}")


def reset_tenant_id(session: Session) -> None:
    """
    Reset the tenant ID session variable.

    Call this after completing tenant-scoped operations to prevent
    data leakage between requests.

    Args:
        session: SQLAlchemy session
    """
    try:
        session.execute(text("RESET app.tenant_id"))
        logger.debug("RLS tenant_id reset")
    except Exception as e:
        # Don't fail if reset fails - just log warning
        logger.warning(f"Failed to reset tenant_id: {e}")


@contextmanager
def tenant_context(
    session: Session, tenant_id: str | UUID
) -> Generator[Session, None, None]:
    """
    Context manager for tenant-scoped database operations.

    Sets the tenant_id for RLS before yielding, and resets it after.
    Use this to ensure proper tenant isolation for all database operations.

    Args:
        session: SQLAlchemy session
        tenant_id: UUID string or UUID object of the tenant

    Yields:
        Session: The same session with tenant_id set

    Usage:
        with tenant_context(db, tenant_id) as session:
            # All queries are automatically filtered by tenant_id
            reservations = session.query(ReservationModel).all()
    """
    try:
        set_tenant_id(session, tenant_id)
        yield session
    finally:
        reset_tenant_id(session)


def init_db() -> None:
    """
    Initialize database tables.

    Creates all tables defined in models if they don't exist.
    """
    try:
        logger.info("Creating database tables...")
        Base.metadata.create_all(bind=engine)
        logger.info("Database tables created successfully")
    except Exception as e:
        logger.error(f"Failed to create database tables: {e}")
        # Don't crash - tables might already exist or need manual creation
        logger.warning(
            "Continuing without table creation - "
            "tables may need to be created manually"
        )


def check_db_connection() -> bool:
    """
    Check if database connection is healthy.

    Returns:
        bool: True if connection is healthy, False otherwise
    """
    try:
        with get_db_context() as db:
            db.execute(text("SELECT 1"))
        return True
    except Exception as e:
        logger.error(f"Database connection check failed: {e}")
        return False


# Initialize tables on module load
init_db()
