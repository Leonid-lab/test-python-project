from dataclasses import dataclass, field

import aio_pika


@dataclass
class FakeMessage:
    body: bytes
    acked: bool = False
    nacked: bool = False
    rejected: bool = False
    nack_requeue: bool | None = None
    reject_requeue: bool | None = None
    extra: dict = field(default_factory=dict)

    async def ack(self) -> None:
        self.acked = True

    async def nack(self, requeue: bool = True) -> None:
        self.nacked = True
        self.nack_requeue = requeue

    async def reject(self, requeue: bool = False) -> None:
        self.rejected = True
        self.reject_requeue = requeue


class QueueMessageAdapter:
    """Delegates ack/nack/reject to a real aio-pika message (for DLQ tests)."""

    def __init__(self, incoming: aio_pika.IncomingMessage) -> None:
        self._incoming = incoming
        self.body = incoming.body
        self.acked = False
        self.rejected = False
        self.reject_requeue: bool | None = None

    async def ack(self) -> None:
        self.acked = True
        await self._incoming.ack()

    async def nack(self, requeue: bool = True) -> None:
        await self._incoming.nack(requeue=requeue)

    async def reject(self, requeue: bool = False) -> None:
        self.rejected = True
        self.reject_requeue = requeue
        await self._incoming.reject(requeue=requeue)
