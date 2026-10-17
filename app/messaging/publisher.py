import asyncio
import json
from typing import Any

import aio_pika
from aio_pika import DeliveryMode, Message
from pamqp.commands import Basic

from app.messaging.constants import EXCHANGE_EVENTS, EXCHANGE_RETRIES, RK_NEW


class PublishConfirmError(Exception):
    pass


class UnroutableMessageError(PublishConfirmError):
    pass


async def publish_with_confirm(
    channel: aio_pika.abc.AbstractChannel,
    exchange_name: str,
    routing_key: str,
    body: dict[str, Any],
    *,
    timeout: float,
) -> None:
    exchange = await channel.get_exchange(exchange_name)
    payload = json.dumps(body, separators=(",", ":")).encode("utf-8")
    message = Message(
        body=payload,
        delivery_mode=DeliveryMode.PERSISTENT,
        content_type="application/json",
        message_id=body.get("event_id"),
    )

    try:
        confirmation = await asyncio.wait_for(
            exchange.publish(
                message,
                routing_key=routing_key,
                mandatory=True,
                timeout=timeout,
            ),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        raise PublishConfirmError("publish confirm timeout") from None

    if isinstance(confirmation, Basic.Nack):
        raise PublishConfirmError("broker nacked publish")
    if isinstance(confirmation, Basic.Reject):
        raise UnroutableMessageError("message returned as unroutable")


async def publish_payment_event(
    channel: aio_pika.abc.AbstractChannel,
    payload: dict[str, Any],
    *,
    timeout: float,
) -> None:
    await publish_with_confirm(
        channel,
        EXCHANGE_EVENTS,
        RK_NEW,
        payload,
        timeout=timeout,
    )


async def publish_retry_event(
    channel: aio_pika.abc.AbstractChannel,
    payload: dict[str, Any],
    attempt: int,
    *,
    timeout: float,
) -> None:
    if attempt == 2:
        rk = "payments.retry.1"
    elif attempt == 3:
        rk = "payments.retry.2"
    else:
        raise ValueError("invalid retry attempt")
    await publish_with_confirm(
        channel,
        EXCHANGE_RETRIES,
        rk,
        payload,
        timeout=timeout,
    )
