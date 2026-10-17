import pytest
import aio_pika

from app.config import get_settings
from app.messaging.constants import (
    EXCHANGE_DLX,
    EXCHANGE_EVENTS,
    EXCHANGE_RETRIES,
    QUEUE_DLQ,
    QUEUE_NEW,
    QUEUE_RETRY_1,
    QUEUE_RETRY_2,
)
from app.messaging.topology import declare_topology

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_t29_topology_declares_queues(test_settings):
    settings = test_settings
    connection = await aio_pika.connect_robust(settings.rabbitmq_url)
    channel = await connection.channel()
    await declare_topology(channel)
    for name in (QUEUE_NEW, QUEUE_RETRY_1, QUEUE_RETRY_2, QUEUE_DLQ):
        queue = await channel.get_queue(name, ensure=False)
        assert queue.name == name
    for ex_name in (EXCHANGE_EVENTS, EXCHANGE_RETRIES, EXCHANGE_DLX):
        exchange = await channel.get_exchange(ex_name, ensure=False)
        assert exchange is not None
    await connection.close()
