import uuid
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.payment import Outbox, Payment, PaymentStatus
from app.services.request_hash import compute_request_hash

EVENT_TYPE_PAYMENT_CREATED = "payment.created"
OUTBOX_PAYLOAD_VERSION = 1


class IdempotencyConflictError(Exception):
    pass


@dataclass
class PaymentCreateResult:
    payment: Payment
    created: bool


def build_outbox_payload(event_id: uuid.UUID, payment_id: uuid.UUID) -> dict:
    return {
        "version": OUTBOX_PAYLOAD_VERSION,
        "event_id": str(event_id),
        "payment_id": str(payment_id),
        "attempt": 1,
    }


async def get_payment_by_id(session: AsyncSession, payment_id: uuid.UUID) -> Payment | None:
    result = await session.execute(select(Payment).where(Payment.id == payment_id))
    return result.scalar_one_or_none()


async def get_payment_by_idempotency_key(
    session: AsyncSession, idempotency_key: str
) -> Payment | None:
    result = await session.execute(
        select(Payment).where(Payment.idempotency_key == idempotency_key)
    )
    return result.scalar_one_or_none()


async def create_payment(
    session: AsyncSession,
    *,
    amount: Decimal,
    currency: str,
    description: str,
    metadata: dict,
    webhook_url: str,
    idempotency_key: str,
) -> PaymentCreateResult:
    request_hash = compute_request_hash(
        amount, currency, description, metadata, webhook_url
    )
    payment_id = uuid.uuid4()
    event_id = uuid.uuid4()

    payment = Payment(
        id=payment_id,
        amount=amount,
        currency=currency,
        description=description,
        payment_metadata=metadata,
        status=PaymentStatus.pending.value,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
        webhook_url=webhook_url,
        webhook_event_id=event_id,
    )
    outbox = Outbox(
        aggregate_id=payment_id,
        event_type=EVENT_TYPE_PAYMENT_CREATED,
        payload=build_outbox_payload(event_id, payment_id),
    )
    session.add(payment)
    session.add(outbox)

    try:
        await session.commit()
        await session.refresh(payment)
        return PaymentCreateResult(payment=payment, created=True)
    except IntegrityError:
        await session.rollback()
        existing = await get_payment_by_idempotency_key(session, idempotency_key)
        if existing is None:
            raise
        if existing.request_hash != request_hash:
            raise IdempotencyConflictError() from None
        return PaymentCreateResult(payment=existing, created=False)
