"""
Database Configuration and Session Management

Provides SQLAlchemy engine, session management, and database utilities.
Supports multitenancy via PostgreSQL RLS (Row-Level Security).
"""

import logging
import os
from collections.abc import Generator
from contextlib import contextmanager
from typing import Any

from sqlalchemy import create_engine, event, text
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


def set_tenant_id(session: Session, tenant_id: str) -> None:
    """
    Set the current tenant ID for RLS (Row-Level Security).

    This sets a PostgreSQL session variable that RLS policies can use
    to filter data by tenant.

    Args:
        session: SQLAlchemy session
        tenant_id: UUID string of the tenant
    """
    session.execute(text(f"SET app.tenant_id = '{tenant_id}'"))


def reset_tenant_id(session: Session) -> None:
    """
    Reset the tenant ID session variable.

    Args:
        session: SQLAlchemy session
    """
    session.execute(text("RESET app.tenant_id"))


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
