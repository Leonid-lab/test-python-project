import os
import uuid
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import Settings, get_settings
from app.db import Base, get_db_session
from app.main_api import create_app


def _worker_schema() -> str:
    worker = os.getenv("PYTEST_XDIST_WORKER", "master")
    return f"pytest_{worker}"


@pytest.fixture
def test_settings(monkeypatch) -> Settings:
    monkeypatch.setenv("API_KEY", "test-api-key-12345678")
    monkeypatch.setenv(
        "DATABASE_URL",
        os.getenv(
            "TEST_DATABASE_URL",
            "postgresql+asyncpg://payments:payments@postgres:5432/payments_test",
        ),
    )
    monkeypatch.setenv(
        "RABBITMQ_URL",
        os.getenv("TEST_RABBITMQ_URL", "amqp://payments:payments@rabbitmq:5672/"),
    )
    monkeypatch.setenv("WEBHOOK_ALLOWED_HOSTS", "localhost,127.0.0.1,example.org,webhook.test")
    monkeypatch.setenv("WEBHOOK_SSRF_RELAXED", "true")
    monkeypatch.setenv("WEBHOOK_ALLOW_HTTP", "true")
    monkeypatch.setenv("GATEWAY_SLEEP_MS", "1")
    monkeypatch.setenv("ENABLE_OPENAPI", "false")
    get_settings.cache_clear()
    return get_settings()


@pytest_asyncio.fixture
async def db_engine(test_settings):
    schema = _worker_schema()
    engine = create_async_engine(
        test_settings.database_url,
        pool_pre_ping=True,
        connect_args={"server_settings": {"search_path": schema}},
    )
    async with engine.begin() as conn:
        await conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{schema}"'))
        await conn.execute(text(f'SET search_path TO "{schema}"'))
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()
    get_settings.cache_clear()


@pytest_asyncio.fixture
async def db_session(db_engine) -> AsyncGenerator[AsyncSession, None]:
    factory = async_sessionmaker(db_engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as session:
        yield session


@pytest_asyncio.fixture
async def api_client(db_engine, test_settings) -> AsyncGenerator[AsyncClient, None]:
    factory = async_sessionmaker(db_engine, expire_on_commit=False, class_=AsyncSession)

    async def override_get_db():
        async with factory() as session:
            yield session

    app = create_app()
    app.dependency_overrides[get_db_session] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    app.dependency_overrides.clear()
    get_settings.cache_clear()


@pytest.fixture
def auth_headers():
    return {
        "X-API-Key": "test-api-key-12345678",
        "Idempotency-Key": str(uuid.uuid4()),
    }


@pytest.fixture
def payment_payload():
    return {
        "amount": "1250.50",
        "currency": "RUB",
        "description": "Order #42",
        "metadata": {"order_id": "42"},
        "webhook_url": "http://127.0.0.1:8080/hook",
    }
