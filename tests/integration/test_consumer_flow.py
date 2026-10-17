"""T15–T25: consumer, webhook retries, DLQ."""

import asyncio
import uuid
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest
from aio_pika import DeliveryMode, Message

from app.gateway import simulator as sim
from app.messaging.constants import EXCHANGE_EVENTS, QUEUE_DLQ, QUEUE_NEW, RK_NEW
from app.messaging.processing import build_message_body, process_payment_message
from app.models.payment import Payment, PaymentStatus, WebhookStatus
from app.services.payment_processing import mark_webhook_delivered
from app.services.payments import create_payment
from tests.helpers import FakeMessage, QueueMessageAdapter

pytestmark = pytest.mark.integration


class _ForcedOutcome:
    def __init__(self, status: str) -> None:
        self._status = status

    def get_outcome(self, _payment_id: uuid.UUID) -> str:
        return self._status


async def _create_pending(
    session_factory,
    webhook_url: str,
    key: str | None = None,
) -> tuple[uuid.UUID, str]:
    async with session_factory() as session:
        result = await create_payment(
            session,
            amount=Decimal("50.00"),
            currency="RUB",
            description="consumer-test",
            metadata={},
            webhook_url=webhook_url,
            idempotency_key=key or f"cf-{uuid.uuid4()}",
        )
        return result.payment.id, str(result.payment.webhook_event_id)


async def _process(
    channel,
    session_factory,
    test_settings,
    payment_id: uuid.UUID,
    event_id: str,
    attempt: int = 1,
) -> FakeMessage:
    msg = FakeMessage(body=build_message_body(payment_id, event_id, attempt))
    await process_payment_message(channel, msg, session_factory, test_settings)
    return msg


@pytest.mark.asyncio
async def test_t15_duplicate_after_delivered_no_reprocess(
    session_factory, test_settings, rabbit_connection, webhook_mock
):
    state, webhook_url = webhook_mock
    payment_id, event_id = await _create_pending(session_factory, webhook_url)
    sim.set_gateway_test_hooks(None, _ForcedOutcome(PaymentStatus.succeeded.value))
    channel = await rabbit_connection.channel(publisher_confirms=True)

    msg1 = await _process(channel, session_factory, test_settings, payment_id, event_id, 1)
    assert msg1.acked
    calls_after_first = len(state.calls)

    msg2 = await _process(channel, session_factory, test_settings, payment_id, event_id, 1)
    assert msg2.acked
    assert len(state.calls) == calls_after_first

    async with session_factory() as session:
        payment = await session.get(Payment, payment_id)
        assert payment.status == PaymentStatus.succeeded.value
    sim.clear_gateway_test_hooks()
    await channel.close()


@pytest.mark.asyncio
async def test_t16_gateway_failed_webhook_payload(
    session_factory, test_settings, rabbit_connection, webhook_mock
):
    state, webhook_url = webhook_mock
    payment_id, event_id = await _create_pending(session_factory, webhook_url)
    sim.set_gateway_test_hooks(None, _ForcedOutcome(PaymentStatus.failed.value))
    channel = await rabbit_connection.channel(publisher_confirms=True)
    msg = await _process(channel, session_factory, test_settings, payment_id, event_id)
    assert msg.acked
    async with session_factory() as session:
        payment = await session.get(Payment, payment_id)
        assert payment.status == PaymentStatus.failed.value
        assert payment.processed_at is not None
    assert state.calls[-1]["body"]["status"] == PaymentStatus.failed.value
    dlq = await channel.get_queue("payments.dlq", ensure=False)
    assert await dlq.get(timeout=1, fail=False) is None
    sim.clear_gateway_test_hooks()
    await channel.close()


@pytest.mark.asyncio
async def test_t17_gateway_succeeded(
    session_factory, test_settings, rabbit_connection, webhook_mock
):
    state, webhook_url = webhook_mock
    payment_id, event_id = await _create_pending(session_factory, webhook_url)
    sim.set_gateway_test_hooks(None, _ForcedOutcome(PaymentStatus.succeeded.value))
    channel = await rabbit_connection.channel(publisher_confirms=True)
    msg = await _process(channel, session_factory, test_settings, payment_id, event_id)
    assert msg.acked
    async with session_factory() as session:
        payment = await session.get(Payment, payment_id)
        assert payment.status == PaymentStatus.succeeded.value
        assert payment.webhook_status == WebhookStatus.delivered.value
    assert state.calls[-1]["body"]["status"] == PaymentStatus.succeeded.value
    sim.clear_gateway_test_hooks()
    await channel.close()


@pytest.mark.asyncio
async def test_t18_webhook_2xx_delivered_once(
    session_factory, test_settings, rabbit_connection, webhook_mock
):
    state, webhook_url = webhook_mock
    payment_id, event_id = await _create_pending(session_factory, webhook_url)
    sim.set_gateway_test_hooks(None, _ForcedOutcome(PaymentStatus.succeeded.value))
    channel = await rabbit_connection.channel(publisher_confirms=True)
    await _process(channel, session_factory, test_settings, payment_id, event_id)
    await _process(channel, session_factory, test_settings, payment_id, event_id)
    assert len(state.calls) == 1
    sim.clear_gateway_test_hooks()
    await channel.close()


@pytest.mark.asyncio
async def test_t19_three_webhook_attempts_then_delivered(
    session_factory, test_settings, rabbit_connection, webhook_mock
):
    state, webhook_url = webhook_mock
    payment_id, event_id = await _create_pending(session_factory, webhook_url)
    sim.set_gateway_test_hooks(None, _ForcedOutcome(PaymentStatus.succeeded.value))
    channel = await rabbit_connection.channel(publisher_confirms=True)

    state.next_status = 500
    msg1 = await _process(channel, session_factory, test_settings, payment_id, event_id, 1)
    assert msg1.acked

    state.next_status = 500
    msg2 = await _process(channel, session_factory, test_settings, payment_id, event_id, 2)
    assert msg2.acked

    state.next_status = 200
    msg3 = await _process(channel, session_factory, test_settings, payment_id, event_id, 3)
    assert msg3.acked

    async with session_factory() as session:
        payment = await session.get(Payment, payment_id)
        assert payment.webhook_status == WebhookStatus.delivered.value
        assert payment.webhook_attempts == 2
    assert len(state.calls) == 3
    sim.clear_gateway_test_hooks()
    await channel.close()


@pytest.mark.asyncio
async def test_t20_webhook_always_500_exhausted_and_dlq(
    session_factory, test_settings, rabbit_connection, webhook_mock
):
    state, webhook_url = webhook_mock
    payment_id, event_id = await _create_pending(session_factory, webhook_url)
    sim.set_gateway_test_hooks(None, _ForcedOutcome(PaymentStatus.succeeded.value))
    channel = await rabbit_connection.channel(publisher_confirms=True)
    state.next_status = 500

    msg1 = await _process(channel, session_factory, test_settings, payment_id, event_id, 1)
    assert msg1.acked
    msg2 = await _process(channel, session_factory, test_settings, payment_id, event_id, 2)
    assert msg2.acked
    async with session_factory() as session:
        payment = await session.get(Payment, payment_id)
        assert payment.webhook_attempts == 2

    exchange = await channel.get_exchange(EXCHANGE_EVENTS)
    await exchange.publish(
        Message(
            body=build_message_body(payment_id, event_id, 3),
            delivery_mode=DeliveryMode.PERSISTENT,
        ),
        routing_key=RK_NEW,
    )
    main_q = await channel.get_queue(QUEUE_NEW, ensure=False)
    incoming = await main_q.get(timeout=5, fail=False)
    assert incoming is not None
    adapter = QueueMessageAdapter(incoming)
    await process_payment_message(channel, adapter, session_factory, test_settings)
    assert adapter.rejected and adapter.reject_requeue is False

    async with session_factory() as session:
        payment = await session.get(Payment, payment_id)
        assert payment.webhook_status == WebhookStatus.exhausted.value

    dlq = await channel.get_queue(QUEUE_DLQ, ensure=False)
    dead = await dlq.get(timeout=5, fail=False)
    assert dead is not None
    await dead.ack()
    sim.clear_gateway_test_hooks()
    await channel.close()


@pytest.mark.asyncio
async def test_t21_redirect_not_followed_retries(
    session_factory, test_settings, rabbit_connection, webhook_mock
):
    state, webhook_url = webhook_mock
    state.redirect_url = "http://127.0.0.1:9/evil"
    payment_id, event_id = await _create_pending(session_factory, webhook_url)
    sim.set_gateway_test_hooks(None, _ForcedOutcome(PaymentStatus.succeeded.value))
    channel = await rabbit_connection.channel(publisher_confirms=True)

    msg = await _process(channel, session_factory, test_settings, payment_id, event_id, 1)
    assert msg.acked
    async with session_factory() as session:
        payment = await session.get(Payment, payment_id)
        assert payment.webhook_attempts == 1
        assert payment.webhook_status == WebhookStatus.pending.value
    state.redirect_url = None
    sim.clear_gateway_test_hooks()
    await channel.close()


@pytest.mark.asyncio
async def test_t22_safe_redelivery_after_terminal(
    session_factory, test_settings, rabbit_connection, webhook_mock
):
    state, webhook_url = webhook_mock
    payment_id, event_id = await _create_pending(session_factory, webhook_url)
    sim.set_gateway_test_hooks(None, _ForcedOutcome(PaymentStatus.succeeded.value))
    channel = await rabbit_connection.channel(publisher_confirms=True)

    msg1 = await _process(channel, session_factory, test_settings, payment_id, event_id)
    assert msg1.acked
    async with session_factory() as session:
        before = await session.get(Payment, payment_id)
        status_before = before.status

    msg2 = await _process(channel, session_factory, test_settings, payment_id, event_id)
    assert msg2.acked
    async with session_factory() as session:
        after = await session.get(Payment, payment_id)
        assert after.status == status_before
    sim.clear_gateway_test_hooks()
    await channel.close()


@pytest.mark.asyncio
async def test_t23_duplicate_webhook_same_event_id(
    session_factory, test_settings, rabbit_connection, webhook_mock, monkeypatch
):
    state, webhook_url = webhook_mock
    payment_id, event_id = await _create_pending(session_factory, webhook_url)
    sim.set_gateway_test_hooks(None, _ForcedOutcome(PaymentStatus.succeeded.value))
    channel = await rabbit_connection.channel(publisher_confirms=True)

    calls: list[int] = []
    original = mark_webhook_delivered

    async def flaky_delivered(session, pid):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("crash before commit")
        await original(session, pid)

    monkeypatch.setattr(
        "app.messaging.processing.mark_webhook_delivered",
        flaky_delivered,
    )

    msg1 = FakeMessage(body=build_message_body(payment_id, event_id, 1))
    with pytest.raises(RuntimeError):
        await process_payment_message(channel, msg1, session_factory, test_settings)
    assert len(state.calls) == 1

    msg2 = await _process(channel, session_factory, test_settings, payment_id, event_id)
    assert msg2.acked
    assert len(state.calls) == 2
    assert state.calls[0]["event_id"] == state.calls[1]["event_id"]
    sim.clear_gateway_test_hooks()
    await channel.close()


@pytest.mark.asyncio
async def test_t24_invalid_message_rejected_to_dlq(
    session_factory, test_settings, rabbit_connection
):
    channel = await rabbit_connection.channel(publisher_confirms=True)
    exchange = await channel.get_exchange(EXCHANGE_EVENTS)
    await exchange.publish(
        Message(body=b"not-json", delivery_mode=DeliveryMode.PERSISTENT),
        routing_key=RK_NEW,
    )
    main_q = await channel.get_queue(QUEUE_NEW, ensure=False)
    incoming = await main_q.get(timeout=5, fail=False)
    assert incoming is not None
    adapter = QueueMessageAdapter(incoming)
    await process_payment_message(channel, adapter, session_factory, test_settings)
    assert adapter.rejected and adapter.reject_requeue is False
    await channel.close()
    dlq_channel = await rabbit_connection.channel()
    dlq = await dlq_channel.get_queue(QUEUE_DLQ, ensure=False)
    dead = None
    for _ in range(30):
        dead = await dlq.get(timeout=0.2, fail=False)
        if dead is not None:
            break
        await asyncio.sleep(0.05)
    assert dead is not None
    await dead.ack()
    await dlq_channel.close()


@pytest.mark.asyncio
async def test_t25_retry_publish_failure_nacks(
    session_factory, test_settings, rabbit_connection, webhook_mock, monkeypatch
):
    state, webhook_url = webhook_mock
    state.next_status = 500
    payment_id, event_id = await _create_pending(session_factory, webhook_url)
    sim.set_gateway_test_hooks(None, _ForcedOutcome(PaymentStatus.succeeded.value))
    channel = await rabbit_connection.channel(publisher_confirms=True)

    monkeypatch.setattr(
        "app.messaging.processing.publish_retry_event",
        AsyncMock(side_effect=RuntimeError("broker down")),
    )

    msg = await _process(channel, session_factory, test_settings, payment_id, event_id, 1)
    assert msg.nacked and msg.nack_requeue is True
    assert not msg.acked
    async with session_factory() as session:
        payment = await session.get(Payment, payment_id)
        assert payment.webhook_attempts == 1
        assert payment.webhook_status == WebhookStatus.pending.value
    sim.clear_gateway_test_hooks()
    await channel.close()
