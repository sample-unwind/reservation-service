import logging
from enum import Enum
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from payment_client import PaymentServiceError, process_payment_for_reservation

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Reservation Service", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ReservationStatus(str, Enum):
    """Reservation status enum matching CQRS event types."""

    CREATED = "RESERVATION_CREATED"
    CONFIRMED = "RESERVATION_CONFIRMED"
    FAILED = "RESERVATION_FAILED"


class CreateReservationRequest(BaseModel):
    """Request model for creating a reservation."""

    user_id: str
    amount: float
    currency: str = "EUR"


class ReservationResponse(BaseModel):
    """Response model for reservation operations."""

    reservation_id: str
    status: ReservationStatus
    transaction_id: Optional[str] = None
    message: str


# In-memory storage for demo (should use a real event store in production)
reservations = {}
reservation_counter = 0


@app.get("/health/live")
def health_live():
    return {"status": "alive"}


@app.get("/health/ready")
def health_ready():
    return {"status": "ready"}


@app.get("/")
def root():
    return {"message": "Reservation Service API"}


@app.post("/reservations", response_model=ReservationResponse)
async def create_reservation(request: CreateReservationRequest):
    """
    Create a new reservation and process payment.

    Flow:
    1. Create reservation (RESERVATION_CREATED event)
    2. Call payment-service via gRPC
    3. If successful → RESERVATION_CONFIRMED event
    4. If failed → RESERVATION_FAILED event
    """
    global reservation_counter

    # Generate reservation ID
    reservation_counter += 1
    reservation_id = f"RES-{reservation_counter:06d}"

    logger.info(
        f"Creating reservation {reservation_id} for user {request.user_id} "
        f"with amount {request.amount} {request.currency}"
    )

    # Step 1: Create reservation (RESERVATION_CREATED event)
    reservations[reservation_id] = {
        "id": reservation_id,
        "user_id": request.user_id,
        "amount": request.amount,
        "currency": request.currency,
        "status": ReservationStatus.CREATED,
    }

    try:
        # Step 2: Call payment-service via gRPC
        logger.info(f"Processing payment for reservation {reservation_id}")
        success, transaction_id, message = process_payment_for_reservation(
            reservation_id=reservation_id,
            user_id=request.user_id,
            amount=request.amount,
            currency=request.currency,
        )

        if success:
            # Step 3: Payment successful → RESERVATION_CONFIRMED
            reservations[reservation_id]["status"] = ReservationStatus.CONFIRMED
            reservations[reservation_id]["transaction_id"] = transaction_id

            logger.info(
                f"Reservation {reservation_id} confirmed with transaction {transaction_id}"
            )

            return ReservationResponse(
                reservation_id=reservation_id,
                status=ReservationStatus.CONFIRMED,
                transaction_id=transaction_id,
                message=f"Reservation confirmed: {message}",
            )
        else:
            # Step 4: Payment failed → RESERVATION_FAILED
            reservations[reservation_id]["status"] = ReservationStatus.FAILED

            logger.warning(f"Reservation {reservation_id} failed: {message}")

            return ReservationResponse(
                reservation_id=reservation_id,
                status=ReservationStatus.FAILED,
                message=f"Reservation failed: {message}",
            )

    except PaymentServiceError as e:
        # Graceful degradation: payment service unavailable
        reservations[reservation_id]["status"] = ReservationStatus.FAILED

        logger.error(
            f"Payment service unavailable for reservation {reservation_id}: {str(e)}"
        )

        raise HTTPException(
            status_code=503,
            detail={
                "reservation_id": reservation_id,
                "status": ReservationStatus.FAILED,
                "message": "Payment service temporarily unavailable. Please try again later.",
            },
        )


@app.get("/reservations/{reservation_id}", response_model=ReservationResponse)
async def get_reservation(reservation_id: str):
    """Get reservation details by ID."""
    if reservation_id not in reservations:
        raise HTTPException(status_code=404, detail="Reservation not found")

    reservation = reservations[reservation_id]

    return ReservationResponse(
        reservation_id=reservation["id"],
        status=reservation["status"],
        transaction_id=reservation.get("transaction_id"),
        message=f"Reservation {reservation['status'].value}",
    )
