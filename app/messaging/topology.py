import aio_pika
from aio_pika import ExchangeType

from app.messaging.constants import (
    EXCHANGE_DLX,
    EXCHANGE_EVENTS,
    EXCHANGE_RETRIES,
    QUEUE_DLQ,
    QUEUE_NEW,
    QUEUE_RETRY_1,
    QUEUE_RETRY_2,
    RK_DEAD,
    RK_NEW,
    RK_RETRY_1,
    RK_RETRY_2,
)


async def declare_topology(channel: aio_pika.abc.AbstractChannel) -> None:
    events = await channel.declare_exchange(
        EXCHANGE_EVENTS, ExchangeType.DIRECT, durable=True
    )
    retries = await channel.declare_exchange(
        EXCHANGE_RETRIES, ExchangeType.DIRECT, durable=True
    )
    dlx = await channel.declare_exchange(EXCHANGE_DLX, ExchangeType.DIRECT, durable=True)

    dlq = await channel.declare_queue(QUEUE_DLQ, durable=True)
    await dlq.bind(dlx, routing_key=RK_DEAD)

    main_q = await channel.declare_queue(
        QUEUE_NEW,
        durable=True,
        arguments={
            "x-dead-letter-exchange": EXCHANGE_DLX,
            "x-dead-letter-routing-key": RK_DEAD,
        },
    )
    await main_q.bind(events, routing_key=RK_NEW)

    retry1 = await channel.declare_queue(
        QUEUE_RETRY_1,
        durable=True,
        arguments={
            "x-message-ttl": 2000,
            "x-dead-letter-exchange": EXCHANGE_EVENTS,
            "x-dead-letter-routing-key": RK_NEW,
        },
    )
    await retry1.bind(retries, routing_key=RK_RETRY_1)

    retry2 = await channel.declare_queue(
        QUEUE_RETRY_2,
        durable=True,
        arguments={
            "x-message-ttl": 4000,
            "x-dead-letter-exchange": EXCHANGE_EVENTS,
            "x-dead-letter-routing-key": RK_NEW,
        },
    )
    await retry2.bind(retries, routing_key=RK_RETRY_2)
