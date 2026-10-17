import uuid
from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.payment import PaymentStatus, WebhookStatus
from app.services.request_hash import normalize_amount

FINALIZE_SQL = text(
    """
    UPDATE payments
    SET status = :status,
        processed_at = :processed_at
    WHERE id = :payment_id AND status = 'pending'
    RETURNING id
    """
)

MARK_DELIVERED_SQL = text(
    """
    UPDATE payments
    SET webhook_status = 'delivered',
        webhook_delivered_at = :delivered_at,
        webhook_last_error = NULL
    WHERE id = :payment_id AND webhook_status != 'delivered'
    """
)

INCREMENT_WEBHOOK_ATTEMPT_SQL = text(
    """
    UPDATE payments
    SET webhook_attempts = webhook_attempts + 1,
        webhook_last_error = :last_error
    WHERE id = :payment_id AND webhook_attempts < 3
    RETURNING webhook_attempts
    """
)

MARK_EXHAUSTED_SQL = text(
    """
    UPDATE payments
    SET webhook_status = 'exhausted',
        webhook_last_error = :last_error
    WHERE id = :payment_id AND webhook_status != 'delivered'
    """
)


async def finalize_payment_if_pending(
    session: AsyncSession, payment_id: uuid.UUID, status: str
) -> bool:
    now = datetime.now(UTC)
    result = await session.execute(
        FINALIZE_SQL,
        {"payment_id": payment_id, "status": status, "processed_at": now},
    )
    return result.fetchone() is not None


async def mark_webhook_delivered(session: AsyncSession, payment_id: uuid.UUID) -> None:
    await session.execute(
        MARK_DELIVERED_SQL,
        {"payment_id": payment_id, "delivered_at": datetime.now(UTC)},
    )


async def increment_webhook_attempt(
    session: AsyncSession, payment_id: uuid.UUID, error: str
) -> int | None:
    result = await session.execute(
        INCREMENT_WEBHOOK_ATTEMPT_SQL,
        {"payment_id": payment_id, "last_error": error[:500]},
    )
    row = result.fetchone()
    return row[0] if row else None


async def mark_webhook_exhausted(session: AsyncSession, payment_id: uuid.UUID, error: str) -> None:
    await session.execute(
        MARK_EXHAUSTED_SQL,
        {"payment_id": payment_id, "last_error": error[:500]},
    )


def build_webhook_payload(payment) -> dict:
    return {
        "event_id": str(payment.webhook_event_id),
        "payment_id": str(payment.id),
        "status": payment.status,
        "amount": normalize_amount(payment.amount),
        "currency": payment.currency,
        "processed_at": payment.processed_at.isoformat() if payment.processed_at else None,
    }


def is_terminal(status: str) -> bool:
    return status in (PaymentStatus.succeeded.value, PaymentStatus.failed.value)
