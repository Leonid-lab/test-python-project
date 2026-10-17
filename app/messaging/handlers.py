import aio_pika
from aio_pika import ExchangeType
from faststream.rabbit import RabbitBroker, RabbitExchange, RabbitMessage, RabbitQueue
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.messaging.constants import EXCHANGE_DLX, EXCHANGE_EVENTS, QUEUE_NEW, RK_DEAD
from app.messaging.processing import process_payment_message
from app.messaging.rabbit_holder import rabbit_connection_holder


def register_handlers(
    broker: RabbitBroker,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    main_queue = RabbitQueue(
        QUEUE_NEW,
        durable=True,
        arguments={
            "x-dead-letter-exchange": EXCHANGE_DLX,
            "x-dead-letter-routing-key": RK_DEAD,
        },
    )
    events_exchange = RabbitExchange(
        EXCHANGE_EVENTS,
        type=ExchangeType.DIRECT,
        durable=True,
    )

    @broker.subscriber(
        main_queue,
        exchange=events_exchange,
        no_ack=False,
        consume_args={"prefetch_count": settings.rabbitmq_prefetch},
    )
    async def handle_payment(msg: RabbitMessage) -> None:
        connection = rabbit_connection_holder.connection
        if connection is None:
            await msg.nack(requeue=True)
            return
        channel = await connection.channel(publisher_confirms=True)
        try:
            await process_payment_message(channel, msg, session_factory, settings)
        finally:
            await channel.close()
