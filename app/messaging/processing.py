import json
import logging
import uuid
from typing import Any, Protocol

import aio_pika
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.gateway.simulator import emulate_gateway
from app.messaging.publisher import publish_retry_event
from app.models.payment import WebhookStatus
from app.services.payment_processing import (
    build_webhook_payload,
    finalize_payment_if_pending,
    increment_webhook_attempt,
    is_terminal,
    mark_webhook_delivered,
    mark_webhook_exhausted,
)
from app.services.payments import get_payment_by_id
from app.webhook.client import WebhookDeliveryError, post_webhook

logger = logging.getLogger(__name__)

OUTBOX_PAYLOAD_VERSION = 1


class IncomingMessage(Protocol):
    body: bytes

    async def ack(self) -> None: ...
    async def nack(self, requeue: bool = True) -> None: ...
    async def reject(self, requeue: bool = False) -> None: ...


def parse_payment_message(body: bytes) -> dict[str, Any]:
    data = json.loads(body.decode("utf-8"))
    if data.get("version") != OUTBOX_PAYLOAD_VERSION:
        raise ValueError("unsupported payload version")
    payment_id = uuid.UUID(str(data["payment_id"]))
    event_id = str(data["event_id"])
    attempt = int(data.get("attempt", 1))
    if attempt < 1 or attempt > 3:
        raise ValueError("invalid attempt")
    return {
        "payment_id": payment_id,
        "event_id": event_id,
        "attempt": attempt,
        "version": OUTBOX_PAYLOAD_VERSION,
    }


def build_message_body(
    payment_id: uuid.UUID,
    event_id: str,
    attempt: int = 1,
) -> bytes:
    payload = {
        "version": OUTBOX_PAYLOAD_VERSION,
        "event_id": event_id,
        "payment_id": str(payment_id),
        "attempt": attempt,
    }
    return json.dumps(payload, separators=(",", ":")).encode("utf-8")


async def process_payment_message(
    channel: aio_pika.abc.AbstractChannel,
    msg: IncomingMessage,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    try:
        parsed = parse_payment_message(msg.body)
    except (json.JSONDecodeError, ValueError, KeyError) as e:
        logger.warning("invalid message: %s", e)
        await msg.reject(requeue=False)
        return

    payment_id = parsed["payment_id"]
    attempt = parsed["attempt"]
    event_id = parsed["event_id"]

    async with session_factory() as session:
        payment = await get_payment_by_id(session, payment_id)
        if payment is None:
            logger.warning("payment not found %s", payment_id)
            await msg.reject(requeue=False)
            return

        if payment.webhook_status == WebhookStatus.exhausted.value:
            await msg.reject(requeue=False)
            return

        if payment.webhook_status == WebhookStatus.delivered.value:
            await msg.ack()
            return

        if not is_terminal(payment.status):
            try:
                outcome = await emulate_gateway(payment_id)
            except Exception:
                await session.rollback()
                await msg.nack(requeue=True)
                return
            finalized = await finalize_payment_if_pending(session, payment_id, outcome)
            await session.commit()
            if not finalized:
                await session.refresh(payment)
            payment = await get_payment_by_id(session, payment_id)
            if payment is None:
                await msg.nack(requeue=True)
                return

    async with session_factory() as session:
        payment = await get_payment_by_id(session, payment_id)
        if payment is None:
            await msg.nack(requeue=True)
            return
        if payment.webhook_status == WebhookStatus.delivered.value:
            await msg.ack()
            return
        if payment.webhook_status == WebhookStatus.exhausted.value:
            await msg.reject(requeue=False)
            return

        payload = build_webhook_payload(payment)
        try:
            await post_webhook(
                payment.webhook_url,
                payload,
                event_id=str(payment.webhook_event_id),
                settings=settings,
            )
        except WebhookDeliveryError as e:
            async with session_factory() as err_session:
                if not e.retryable:
                    await mark_webhook_exhausted(err_session, payment_id, str(e))
                    await err_session.commit()
                    await msg.ack()
                    return
                new_count = await increment_webhook_attempt(err_session, payment_id, str(e))
                await err_session.commit()
                if new_count is None:
                    payment2 = await get_payment_by_id(err_session, payment_id)
                    if payment2 and payment2.webhook_status == WebhookStatus.delivered.value:
                        await msg.ack()
                        return
                    await mark_webhook_exhausted(err_session, payment_id, str(e))
                    await err_session.commit()
                    await msg.reject(requeue=False)
                    return
                if attempt >= 3:
                    await mark_webhook_exhausted(err_session, payment_id, str(e))
                    await err_session.commit()
                    await msg.reject(requeue=False)
                    return
                retry_body = {
                    "version": OUTBOX_PAYLOAD_VERSION,
                    "event_id": event_id,
                    "payment_id": str(payment_id),
                    "attempt": attempt + 1,
                }
                try:
                    await publish_retry_event(
                        channel,
                        retry_body,
                        attempt + 1,
                        timeout=settings.outbox_publish_timeout_sec,
                    )
                except Exception:
                    await msg.nack(requeue=True)
                    return
                await msg.ack()
                return
        except Exception:
            await msg.nack(requeue=True)
            return

        await mark_webhook_delivered(session, payment_id)
        await session.commit()
        await msg.ack()
