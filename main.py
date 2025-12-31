"""
Reservation Service - Main Application

FastAPI application for managing parking reservations.
Implements CQRS/Event Sourcing pattern with GraphQL API.

Features:
- GraphQL API for reservation CRUD operations
- Event Sourcing for audit trail and state reconstruction
- Multitenancy support via PostgreSQL RLS
- Keycloak authentication integration
- Health check endpoints for Kubernetes probes
"""

import logging
import os
from typing import Any

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from keycloak import KeycloakOpenID
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session
from strawberry.fastapi import GraphQLRouter

from db import check_db_connection, get_db
from schema import schema

# =============================================================================
# Logging Configuration
# =============================================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# =============================================================================
# Pydantic Models for API Responses
# =============================================================================


class HealthResponse(BaseModel):
    """Health check response model."""

    status: str
    service: str = "reservation-service"
    version: str = "1.0.0"


class ReservationStatsResponse(BaseModel):
    """Reservation statistics response model."""

    total_reservations: int
    active_reservations: int
    pending_reservations: int
    completed_reservations: int


# =============================================================================
# FastAPI Application
# =============================================================================

app = FastAPI(
    title="Reservation Service API",
    description=(
        "A reservation management microservice for the Parkora smart parking system. "
        "Provides GraphQL API for creating, managing, and querying parking reservations. "
        "Implements CQRS/Event Sourcing pattern for reliable event tracking and audit trails."
    ),
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    root_path="/api/v1/reservation",
    contact={
        "name": "Parkora Team",
        "url": "https://parkora.crn.si",
    },
    license_info={
        "name": "MIT",
    },
)

# OpenAPI servers configuration
app.servers = [{"url": "https://parkora.crn.si", "description": "Production server"}]

# =============================================================================
# Keycloak Configuration
# =============================================================================

KEYCLOAK_URL = os.getenv("KEYCLOAK_URL", "https://keycloak.parkora.crn.si/auth/")
KEYCLOAK_REALM = os.getenv("KEYCLOAK_REALM", "parkora")
KEYCLOAK_CLIENT_ID = os.getenv("KEYCLOAK_CLIENT_ID", "backend-services")
KEYCLOAK_CLIENT_SECRET = os.getenv("KEYCLOAK_CLIENT_SECRET")

keycloak_openid = KeycloakOpenID(
    server_url=KEYCLOAK_URL,
    client_id=KEYCLOAK_CLIENT_ID,
    realm_name=KEYCLOAK_REALM,
    client_secret_key=KEYCLOAK_CLIENT_SECRET,
)

# =============================================================================
# CORS Middleware
# =============================================================================

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =============================================================================
# Authentication Helpers
# =============================================================================


def get_current_user(request: Request) -> dict[str, Any] | None:
    """
    Extract and verify JWT token from Authorization header.

    Args:
        request: FastAPI request object

    Returns:
        Token info dict if valid, None otherwise
    """
    auth_header = request.headers.get("authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        return None

    token = auth_header.split(" ")[1]
    try:
        # Verify token with Keycloak
        token_info = keycloak_openid.introspect(token)
        if not token_info.get("active", False):
            return None
        return token_info
    except Exception as e:
        logger.warning(f"Token verification failed: {e}")
        return None


def get_tenant_id(request: Request) -> str | None:
    """
    Extract tenant ID from request headers.

    Args:
        request: FastAPI request object

    Returns:
        Tenant ID string or None
    """
    return request.headers.get("x-tenant-id")


# =============================================================================
# GraphQL Context
# =============================================================================


def get_context(
    request: Request,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """
    Create GraphQL context with database session and user info.

    Args:
        request: FastAPI request object
        db: SQLAlchemy database session

    Returns:
        Context dictionary for GraphQL resolvers
    """
    current_user = get_current_user(request)
    tenant_id = get_tenant_id(request)

    # If no tenant ID provided, try to get from user token
    if not tenant_id and current_user:
        tenant_id = current_user.get("tenant_id")

    return {
        "db": db,
        "current_user": current_user,
        "tenant_id": tenant_id,
        "request": request,
    }


# =============================================================================
# Mount GraphQL Router
# =============================================================================

graphql_app = GraphQLRouter(schema, context_getter=get_context)
app.include_router(graphql_app, prefix="/graphql")

# =============================================================================
# Health Check Endpoints
# =============================================================================


@app.get(
    "/health/live",
    response_model=HealthResponse,
    summary="Liveness Health Check",
    description="Check if the service is alive and responding to requests.",
    tags=["Health"],
)
def health_live() -> HealthResponse:
    """
    Liveness probe - indicates if the service is running.

    Used by Kubernetes to determine if the pod should be restarted.
    """
    return HealthResponse(status="alive")


@app.get(
    "/health/ready",
    response_model=HealthResponse,
    summary="Readiness Health Check",
    description="Check if the service is ready to handle requests, including database connectivity.",
    tags=["Health"],
)
def health_ready(db: Session = Depends(get_db)) -> HealthResponse:
    """
    Readiness probe - indicates if the service is ready to handle traffic.

    Checks database connectivity before reporting ready status.
    Used by Kubernetes to determine if traffic should be routed to the pod.
    """
    try:
        # Test database connectivity
        db.execute(text("SELECT 1"))
        return HealthResponse(status="ready")
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return HealthResponse(status="unhealthy")


# =============================================================================
# API Endpoints
# =============================================================================


@app.get(
    "/",
    summary="API Root",
    description="Welcome endpoint for the Reservation Service API.",
    tags=["General"],
)
def root() -> dict[str, Any]:
    """Root endpoint providing basic API information."""
    return {
        "message": "Reservation Service API",
        "version": "1.0.0",
        "docs": "/docs",
        "graphql": "/graphql",
        "health": {
            "live": "/health/live",
            "ready": "/health/ready",
        },
        "features": [
            "GraphQL API for reservations",
            "CQRS/Event Sourcing pattern",
            "Multitenancy support",
            "Keycloak authentication",
        ],
    }


@app.get(
    "/stats",
    response_model=ReservationStatsResponse,
    summary="Reservation Statistics",
    description="Get basic statistics about reservations in the system.",
    tags=["Analytics"],
)
def get_reservation_stats(
    request: Request,
    db: Session = Depends(get_db),
) -> ReservationStatsResponse:
    """
    Get reservation statistics for monitoring and analytics.

    Returns counts of reservations by status for the current tenant.
    """
    from models import ReservationModel, ReservationStatus

    try:
        tenant_id = get_tenant_id(request)

        # Build base query
        base_query = db.query(ReservationModel)
        if tenant_id:
            from uuid import UUID

            base_query = base_query.filter(
                ReservationModel.tenant_id == UUID(tenant_id)
            )

        # Count by status
        total = base_query.count()

        active = base_query.filter(
            ReservationModel.status == ReservationStatus.CONFIRMED.value
        ).count()

        pending = base_query.filter(
            ReservationModel.status == ReservationStatus.PENDING.value
        ).count()

        completed = base_query.filter(
            ReservationModel.status == ReservationStatus.COMPLETED.value
        ).count()

        return ReservationStatsResponse(
            total_reservations=total,
            active_reservations=active,
            pending_reservations=pending,
            completed_reservations=completed,
        )
    except Exception as e:
        logger.error(f"Failed to get reservation stats: {e}")
        return ReservationStatsResponse(
            total_reservations=0,
            active_reservations=0,
            pending_reservations=0,
            completed_reservations=0,
        )


# =============================================================================
# Startup/Shutdown Events
# =============================================================================


@app.on_event("startup")
async def startup_event() -> None:
    """Application startup event handler."""
    logger.info("Reservation Service starting up...")
    if check_db_connection():
        logger.info("Database connection verified")
    else:
        logger.warning("Database connection could not be verified")


@app.on_event("shutdown")
async def shutdown_event() -> None:
    """Application shutdown event handler."""
    logger.info("Reservation Service shutting down...")
