import logging

import aio_pika
from faststream import FastStream
from faststream.rabbit import RabbitBroker
from sqlalchemy import text

from app.config import get_settings
from app.db import async_session_factory, engine
from app.messaging.handlers import register_handlers
from app.messaging.outbox_publisher import OutboxPublisher
from app.messaging.rabbit_holder import rabbit_connection_holder
from app.messaging.topology import declare_topology

logger = logging.getLogger(__name__)

settings = get_settings()
broker = RabbitBroker(settings.rabbitmq_url)
register_handlers(broker, async_session_factory, settings)
app = FastStream(broker)

_publisher: OutboxPublisher | None = None
_rabbit_connection: aio_pika.abc.AbstractConnection | None = None


async def wait_for_db(max_attempts: int = 60, delay: float = 2.0) -> None:
    import asyncio

    for attempt in range(max_attempts):
        try:
            async with async_session_factory() as session:
                await session.execute(text("SELECT 1"))
            return
        except Exception:
            if attempt == max_attempts - 1:
                raise
            await asyncio.sleep(delay)


@app.on_startup
async def on_startup() -> None:
    import asyncio

    global _publisher, _rabbit_connection
    logging.basicConfig(level=logging.INFO)
    await wait_for_db()

    for attempt in range(60):
        try:
            _rabbit_connection = await aio_pika.connect_robust(settings.rabbitmq_url, timeout=10)
            channel = await _rabbit_connection.channel()
            await declare_topology(channel)
            await channel.close()
            break
        except Exception:
            if attempt == 59:
                raise
            await asyncio.sleep(2)

    rabbit_connection_holder.connection = _rabbit_connection
    _publisher = OutboxPublisher(async_session_factory, settings, _rabbit_connection)
    await _publisher.start()
    logger.info("consumer started")


@app.on_shutdown
async def on_shutdown() -> None:
    global _publisher, _rabbit_connection
    if _publisher is not None:
        await _publisher.stop()
        _publisher = None
    if _rabbit_connection is not None:
        await _rabbit_connection.close()
        _rabbit_connection = None
    rabbit_connection_holder.connection = None
    await engine.dispose()
    logger.info("consumer stopped")
