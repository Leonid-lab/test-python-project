import fcntl
from collections.abc import AsyncGenerator
from pathlib import Path

import aio_pika
import pytest
import pytest_asyncio
from aiohttp import web
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.messaging.topology import declare_topology


class WebhookMockState:
    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.next_status: int = 200
        self.redirect_url: str | None = None

    def reset(self) -> None:
        self.calls.clear()
        self.next_status = 200
        self.redirect_url = None


@pytest_asyncio.fixture
async def session_factory(db_engine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(db_engine, expire_on_commit=False, class_=AsyncSession)


@pytest.fixture
def infra_lock():
    """One worker at a time: shared RabbitMQ queues and webhook port 8080."""
    path = Path("/tmp/pytest-payments-infra.lock")
    handle = path.open("w")
    fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
    try:
        yield
    finally:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()


@pytest_asyncio.fixture
async def rabbit_connection(test_settings, infra_lock):
    connection = await aio_pika.connect_robust(test_settings.rabbitmq_url)
    channel = await connection.channel()
    await declare_topology(channel)
    for name in ("payments.new", "payments.retry.1", "payments.retry.2", "payments.dlq"):
        try:
            queue = await channel.get_queue(name, ensure=False)
            await queue.purge()
        except Exception:
            pass
    await channel.close()
    try:
        yield connection
    finally:
        await connection.close()


@pytest_asyncio.fixture
async def webhook_mock(infra_lock) -> AsyncGenerator[tuple[WebhookMockState, str], None]:
    state = WebhookMockState()

    async def handler(request: web.Request) -> web.Response:
        if state.redirect_url:
            return web.Response(status=302, headers={"Location": state.redirect_url})
        try:
            body = await request.json()
        except Exception:
            body = {}
        state.calls.append(
            {
                "body": body,
                "event_id": request.headers.get("X-Event-ID"),
            }
        )
        return web.Response(status=state.next_status, text="ok")

    app = web.Application()
    app.router.add_post("/hook", handler)
    runner = web.AppRunner(app)
    await runner.setup()
    # SSRF policy allows only 80/443/8080/8443; tests use 8080.
    site = web.TCPSite(runner, "127.0.0.1", 8080)
    await site.start()
    url = "http://127.0.0.1:8080/hook"
    try:
        yield state, url
    finally:
        await runner.cleanup()
