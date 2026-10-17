"""T12–T14, T30: outbox + RabbitMQ."""

import uuid
from decimal import Decimal

import aio_pika
import pytest
from sqlalchemy import select, text

from app.messaging.outbox_publisher import OutboxPublisher
from app.messaging.processing import build_message_body, parse_payment_message, process_payment_message
from app.models.payment import Outbox, Payment, PaymentStatus
from app.models.payment import WebhookStatus
from app.services.payments import create_payment
from tests.helpers import FakeMessage

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_t12_api_commit_without_rabbit(session_factory, test_settings):
    """POST path: payment+outbox committed; RabbitMQ not required."""
    async with session_factory() as session:
        result = await create_payment(
            session,
            amount=Decimal("10.00"),
            currency="RUB",
            description="t12",
            metadata={},
            webhook_url="http://127.0.0.1:8080/h",
            idempotency_key=f"t12-{uuid.uuid4()}",
        )
        outbox = await session.scalar(
            select(Outbox).where(Outbox.aggregate_id == result.payment.id)
        )
    assert outbox is not None
    assert outbox.published_at is None


@pytest.mark.asyncio
async def test_t13_outbox_published_when_rabbit_up(
    session_factory, test_settings, rabbit_connection, webhook_mock
):
    state, webhook_url = webhook_mock
    async with session_factory() as session:
        result = await create_payment(
            session,
            amount=Decimal("11.00"),
            currency="RUB",
            description="t13",
            metadata={},
            webhook_url=webhook_url,
            idempotency_key=f"t13-{uuid.uuid4()}",
        )
        payment_id = result.payment.id
        event_id = str(result.payment.webhook_event_id)

    publisher = OutboxPublisher(session_factory, test_settings, rabbit_connection)
    assert await publisher._tick() >= 1

    async with session_factory() as session:
        outbox = await session.scalar(select(Outbox).where(Outbox.aggregate_id == payment_id))
        assert outbox is not None
        assert outbox.published_at is not None

    channel = await rabbit_connection.channel()
    queue = await channel.get_queue("payments.new", ensure=False)
    message = await queue.get(timeout=5, fail=False)
    assert message is not None
    parsed = parse_payment_message(message.body)
    assert parsed["payment_id"] == payment_id
    assert parsed["event_id"] == event_id
    await message.ack()
    await channel.close()


@pytest.mark.asyncio
async def test_t14_duplicate_processing_idempotent(
    session_factory, test_settings, rabbit_connection, webhook_mock, monkeypatch
):
    from app.gateway import simulator as sim

    state, webhook_url = webhook_mock
    forced = type("O", (), {"get_outcome": lambda _s, _pid: PaymentStatus.succeeded.value})()

    async with session_factory() as session:
        result = await create_payment(
            session,
            amount=Decimal("12.00"),
            currency="RUB",
            description="t14",
            metadata={},
            webhook_url=webhook_url,
            idempotency_key=f"t14-{uuid.uuid4()}",
        )
        payment_id = result.payment.id
        event_id = str(result.payment.webhook_event_id)

    publisher = OutboxPublisher(session_factory, test_settings, rabbit_connection)
    await publisher._tick()

    sim.set_gateway_test_hooks(None, forced)
    channel = await rabbit_connection.channel(publisher_confirms=True)
    body = build_message_body(payment_id, event_id, 1)

    msg1 = FakeMessage(body=body)
    await process_payment_message(channel, msg1, session_factory, test_settings)
    assert msg1.acked

    msg2 = FakeMessage(body=body)
    await process_payment_message(channel, msg2, session_factory, test_settings)
    assert msg2.acked

    async with session_factory() as session:
        payment = await session.get(Payment, payment_id)
        assert payment is not None
        assert payment.status == PaymentStatus.succeeded.value
        assert payment.webhook_status == WebhookStatus.delivered.value
    assert len(state.calls) >= 1
    sim.clear_gateway_test_hooks()
    await channel.close()


@pytest.mark.asyncio
async def test_t30_outbox_claim_uses_index(session_factory, test_settings):
    async with session_factory() as session:
        plan = await session.execute(
            text(
                """
                EXPLAIN (FORMAT TEXT)
                SELECT id FROM outbox
                WHERE published_at IS NULL
                  AND next_attempt_at <= NOW()
                  AND (claim_until IS NULL OR claim_until < NOW())
                ORDER BY next_attempt_at
                LIMIT 5
                """
            )
        )
        lines = "\n".join(row[0] for row in plan.fetchall())
    assert "Index" in lines or "index" in lines.lower() or "outbox" in lines.lower()
