"""
Parking Service Client

HTTP client for communicating with the parking-service microservice.
Provides methods for checking parking spot availability and details.
"""

import logging
import os
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# Service configuration
PARKING_SERVICE_URL = os.getenv(
    "PARKING_SERVICE_URL",
    "https://parkora.crn.si/api/v1/parking",
)
PARKING_SERVICE_TIMEOUT = float(os.getenv("PARKING_SERVICE_TIMEOUT", "10.0"))


class ParkingServiceError(Exception):
    """Exception raised when parking service communication fails."""

    pass


class ParkingClient:
    """
    HTTP client for parking-service.

    Provides methods to:
    - Get parking spot details
    - Check availability
    - Get current occupancy
    """

    def __init__(
        self,
        base_url: str = PARKING_SERVICE_URL,
        timeout: float = PARKING_SERVICE_TIMEOUT,
        auth_token: str | None = None,
    ):
        """
        Initialize parking client.

        Args:
            base_url: Base URL of the parking service
            timeout: Request timeout in seconds
            auth_token: Optional JWT token for authentication
        """
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.auth_token = auth_token
        headers = {}
        if auth_token:
            headers["Authorization"] = f"Bearer {auth_token}"
        self._client = httpx.Client(timeout=timeout, headers=headers)

    def __enter__(self) -> "ParkingClient":
        """Context manager entry."""
        return self

    def __exit__(self, *args: Any) -> None:
        """Context manager exit."""
        self.close()

    def close(self) -> None:
        """Close the HTTP client."""
        self._client.close()

    def get_parking_spots(self) -> list[dict[str, Any]]:
        """
        Get list of all parking spots.

        Returns:
            List of parking spot dictionaries
        """
        try:
            response = self._client.get(f"{self.base_url}/analytics/parkings")
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as e:
            logger.error(f"Failed to get parking spots: {e}")
            raise ParkingServiceError(f"Failed to get parking spots: {e}") from e

    def get_parking_spot(self, spot_id: str) -> dict[str, Any] | None:
        """
        Get details of a specific parking spot.

        Args:
            spot_id: ID of the parking spot

        Returns:
            Parking spot details or None if not found
        """
        try:
            spots = self.get_parking_spots()
            for spot in spots:
                if str(spot.get("id")) == spot_id:
                    return spot
            return None
        except ParkingServiceError:
            return None

    def get_current_availability(self) -> list[dict[str, Any]]:
        """
        Get current availability of all parking spots.

        Returns:
            List of availability data dictionaries
        """
        try:
            response = self._client.get(
                f"{self.base_url}/analytics/availability/current"
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as e:
            logger.error(f"Failed to get availability: {e}")
            raise ParkingServiceError(f"Failed to get availability: {e}") from e

    def check_spot_exists(self, spot_id: str) -> bool:
        """
        Check if a parking spot exists.

        Args:
            spot_id: ID of the parking spot

        Returns:
            True if the spot exists, False otherwise
        """
        spot = self.get_parking_spot(spot_id)
        return spot is not None

    def get_spot_availability(self, spot_id: str) -> dict[str, Any] | None:
        """
        Get availability for a specific parking spot.

        Args:
            spot_id: ID of the parking spot

        Returns:
            Availability data or None if not found
        """
        try:
            availabilities = self.get_current_availability()
            for avail in availabilities:
                if str(avail.get("parking_id")) == spot_id:
                    return avail
            return None
        except ParkingServiceError:
            return None


# Singleton instance for convenience
_client: ParkingClient | None = None


def get_parking_client(auth_token: str | None = None) -> ParkingClient:
    """
    Get or create a parking client.

    Args:
        auth_token: Optional JWT token for authentication.
                   If provided, creates a new client with auth.
                   If not provided, returns singleton unauthenticated client.

    Returns:
        ParkingClient instance
    """
    global _client
    if auth_token:
        # Create new client with authentication token
        return ParkingClient(auth_token=auth_token)
    # Return singleton for unauthenticated calls
    if _client is None:
        _client = ParkingClient()
    return _client


async def async_check_parking_spot(spot_id: str, auth_token: str | None = None) -> bool:
    """
    Async wrapper for checking parking spot existence.

    Args:
        spot_id: ID of the parking spot
        auth_token: Optional JWT token for authentication

    Returns:
        True if the spot exists, False otherwise
    """
    headers = {}
    if auth_token:
        headers["Authorization"] = f"Bearer {auth_token}"

    async with httpx.AsyncClient(timeout=PARKING_SERVICE_TIMEOUT) as client:
        try:
            response = await client.get(
                f"{PARKING_SERVICE_URL}/analytics/parkings",
                headers=headers,
            )
            response.raise_for_status()
            spots = response.json()
            return any(str(spot.get("id")) == spot_id for spot in spots)
        except httpx.HTTPError as e:
            logger.error(f"Failed to check parking spot: {e}")
            return False
