import os
import uuid

import pytest
from sqlalchemy import func, select, text

from app.models.payment import Outbox, Payment
from app.services.payments import create_payment

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_t11_payment_without_outbox_rollback(db_session):
    from decimal import Decimal

    from app.models.payment import Payment as PaymentModel

    payment = PaymentModel(
        id=uuid.uuid4(),
        amount=Decimal("1.00"),
        currency="RUB",
        description="x",
        payment_metadata={},
        idempotency_key=f"rollback-{uuid.uuid4()}",
        request_hash="a" * 64,
        webhook_url="http://127.0.0.1/h",
        webhook_event_id=uuid.uuid4(),
    )
    db_session.add(payment)
    await db_session.flush()
    await db_session.rollback()
    count = await db_session.scalar(select(func.count()).select_from(Payment))
    assert count == 0


@pytest.mark.asyncio
async def test_create_payment_writes_outbox(db_session):
    from decimal import Decimal

    key = f"outbox-{uuid.uuid4()}"
    result = await create_payment(
        db_session,
        amount=Decimal("10.00"),
        currency="RUB",
        description="d",
        metadata={},
        webhook_url="http://127.0.0.1/h",
        idempotency_key=key,
    )
    assert result.created
    outbox = await db_session.scalar(select(Outbox).where(Outbox.aggregate_id == result.payment.id))
    assert outbox is not None
    assert outbox.published_at is None
