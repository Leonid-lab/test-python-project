import asyncio
import logging
import uuid
from datetime import UTC, datetime, timedelta

import aio_pika
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.messaging.publisher import publish_payment_event
from app.messaging.topology import declare_topology

logger = logging.getLogger(__name__)


CLAIM_SQL = text(
    """
    WITH picked AS (
        SELECT id
        FROM outbox
        WHERE published_at IS NULL
          AND next_attempt_at <= NOW()
          AND (claim_until IS NULL OR claim_until < NOW())
        ORDER BY next_attempt_at
        FOR UPDATE SKIP LOCKED
        LIMIT :batch_size
    )
    UPDATE outbox o
    SET claim_token = :claim_token,
        claim_until = NOW() + (:claim_sec * INTERVAL '1 second')
    FROM picked
    WHERE o.id = picked.id
    RETURNING o.id, o.payload
    """
)

MARK_PUBLISHED_SQL = text(
    """
    UPDATE outbox
    SET published_at = NOW(),
        claim_token = NULL,
        claim_until = NULL,
        last_error = NULL
    WHERE id = :id AND claim_token = :claim_token AND published_at IS NULL
    """
)

FAIL_PUBLISH_SQL = text(
    """
    UPDATE outbox
    SET publish_attempts = publish_attempts + 1,
        last_error = :last_error,
        next_attempt_at = NOW() + (:backoff_sec * INTERVAL '1 second'),
        claim_token = NULL,
        claim_until = NULL
    WHERE id = :id AND claim_token = :claim_token AND published_at IS NULL
    """
)


def _backoff_seconds(attempts: int) -> int:
    return min(60, 2 ** min(attempts, 6))


class OutboxPublisher:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        settings: Settings,
        connection: aio_pika.abc.AbstractConnection,
    ):
        self._session_factory = session_factory
        self._settings = settings
        self._connection = connection
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()

    async def start(self) -> None:
        channel = await self._connection.channel(publisher_confirms=True)
        await declare_topology(channel)
        await channel.close()
        self._stop.clear()
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        self._stop.set()
        if self._task:
            await self._task

    async def _run(self) -> None:
        while not self._stop.is_set():
            try:
                processed = await self._tick()
                if processed == 0:
                    try:
                        await asyncio.wait_for(
                            self._stop.wait(),
                            timeout=self._settings.outbox_poll_interval_sec,
                        )
                    except TimeoutError:
                        pass
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("outbox publisher tick failed")
                await asyncio.sleep(self._settings.outbox_poll_interval_sec)

    async def _tick(self) -> int:
        claim_token = uuid.uuid4()
        rows: list[tuple] = []
        async with self._session_factory() as session:
            result = await session.execute(
                CLAIM_SQL,
                {
                    "batch_size": self._settings.outbox_batch_size,
                    "claim_token": claim_token,
                    "claim_sec": self._settings.outbox_claim_sec,
                },
            )
            rows = list(result.fetchall())
            await session.commit()

        if not rows:
            return 0

        channel = await self._connection.channel(publisher_confirms=True)
        try:
            await declare_topology(channel)
            for row_id, payload in rows:
                await self._publish_one(channel, row_id, claim_token, payload)
        finally:
            await channel.close()
        return len(rows)

    async def _publish_one(
        self,
        channel: aio_pika.abc.AbstractChannel,
        row_id: uuid.UUID,
        claim_token: uuid.UUID,
        payload: dict,
    ) -> None:
        body = dict(payload)
        body.setdefault("attempt", 1)
        try:
            await publish_payment_event(
                channel,
                body,
                timeout=self._settings.outbox_publish_timeout_sec,
            )
            async with self._session_factory() as session:
                await session.execute(
                    MARK_PUBLISHED_SQL,
                    {"id": row_id, "claim_token": claim_token},
                )
                await session.commit()
        except Exception as e:
            err = str(e)[:500]
            async with self._session_factory() as session:
                count_res = await session.execute(
                    text("SELECT publish_attempts FROM outbox WHERE id = :id"),
                    {"id": row_id},
                )
                attempts = count_res.scalar_one_or_none() or 0
                await session.execute(
                    FAIL_PUBLISH_SQL,
                    {
                        "id": row_id,
                        "claim_token": claim_token,
                        "last_error": err,
                        "backoff_sec": _backoff_seconds(attempts + 1),
                    },
                )
                await session.commit()
            logger.warning("outbox publish failed id=%s: %s", row_id, err)
