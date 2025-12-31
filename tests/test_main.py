"""
Test Main Application

Tests for health endpoints and basic API functionality.
"""

import os

# Set environment variable before importing main
os.environ["DATABASE_URL"] = "sqlite+pysqlite:///:memory:"

from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


def test_health_live():
    """Test liveness health check endpoint."""
    response = client.get("/health/live")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "alive"
    assert data["service"] == "reservation-service"
    assert data["version"] == "1.0.0"


def test_health_ready():
    """Test readiness health check endpoint."""
    response = client.get("/health/ready")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] in ["ready", "unhealthy"]
    assert data["service"] == "reservation-service"


def test_root():
    """Test root endpoint."""
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["message"] == "Reservation Service API"
    assert data["version"] == "1.0.0"
    assert "graphql" in data
    assert "health" in data
    assert "features" in data


def test_root_contains_features():
    """Test that root endpoint lists features."""
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    features = data["features"]
    assert "GraphQL API for reservations" in features
    assert "CQRS/Event Sourcing pattern" in features


def test_stats_endpoint():
    """Test statistics endpoint."""
    response = client.get("/stats")
    assert response.status_code == 200
    data = response.json()
    assert "total_reservations" in data
    assert "active_reservations" in data
    assert "pending_reservations" in data
    assert "completed_reservations" in data


def test_graphql_endpoint_exists():
    """Test that GraphQL endpoint is accessible."""
    # Simple introspection query
    query = """
    query {
        __schema {
            types {
                name
            }
        }
    }
    """
    response = client.post("/graphql", json={"query": query})
    assert response.status_code == 200
    data = response.json()
    assert "data" in data
    assert "__schema" in data["data"]
