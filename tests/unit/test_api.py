import asyncio
import uuid

import pytest
from sqlalchemy import func, select

from app.models.payment import Outbox, Payment

pytestmark = pytest.mark.unit


@pytest.mark.asyncio
async def test_t01_post_valid(api_client, auth_headers, payment_payload):
    headers = {**auth_headers, "Idempotency-Key": "t01-key"}
    resp = await api_client.post("/api/v1/payments", json=payment_payload, headers=headers)
    assert resp.status_code == 202
    data = resp.json()
    assert data["status"] == "pending"
    uuid.UUID(data["payment_id"])
    assert data["created_at"].endswith("Z") or "+" in data["created_at"]


@pytest.mark.asyncio
async def test_t03_unauthorized(api_client, payment_payload):
    resp = await api_client.post(
        "/api/v1/payments",
        json=payment_payload,
        headers={"Idempotency-Key": "x"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_t04_no_idempotency(api_client, auth_headers, payment_payload):
    resp = await api_client.post(
        "/api/v1/payments",
        json=payment_payload,
        headers={"X-API-Key": auth_headers["X-API-Key"]},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_t05_idempotent_repeat(api_client, auth_headers, payment_payload, db_session):
    headers = {**auth_headers, "Idempotency-Key": "idem-repeat"}
    r1 = await api_client.post("/api/v1/payments", json=payment_payload, headers=headers)
    r2 = await api_client.post("/api/v1/payments", json=payment_payload, headers=headers)
    assert r1.status_code == r2.status_code == 202
    assert r1.json()["payment_id"] == r2.json()["payment_id"]
    count = await db_session.scalar(select(func.count()).select_from(Payment))
    outbox_count = await db_session.scalar(select(func.count()).select_from(Outbox))
    assert count == 1
    assert outbox_count == 1


@pytest.mark.asyncio
async def test_t06_idempotent_conflict(api_client, auth_headers, payment_payload):
    headers = {**auth_headers, "Idempotency-Key": "idem-conflict"}
    r1 = await api_client.post("/api/v1/payments", json=payment_payload, headers=headers)
    assert r1.status_code == 202
    other = {**payment_payload, "amount": "99.99"}
    r2 = await api_client.post("/api/v1/payments", json=other, headers=headers)
    assert r2.status_code == 409


@pytest.mark.asyncio
async def test_t07_concurrent_idempotency(api_client, auth_headers, payment_payload, db_session):
    headers = {**auth_headers, "Idempotency-Key": "concurrent-key"}

    async def post_once():
        return await api_client.post("/api/v1/payments", json=payment_payload, headers=headers)

    results = await asyncio.gather(*[post_once() for _ in range(20)])
    assert all(r.status_code == 202 for r in results)
    ids = {r.json()["payment_id"] for r in results}
    assert len(ids) == 1
    count = await db_session.scalar(select(func.count()).select_from(Payment))
    outbox_count = await db_session.scalar(select(func.count()).select_from(Outbox))
    assert count == 1
    assert outbox_count == 1


@pytest.mark.asyncio
async def test_t08_invalid_amount(api_client, auth_headers, payment_payload):
    headers = {**auth_headers, "Idempotency-Key": "bad-amount"}
    for amount in ["0", "-1", "1.001"]:
        payload = {**payment_payload, "amount": amount}
        resp = await api_client.post("/api/v1/payments", json=payload, headers=headers)
        assert resp.status_code == 422


@pytest.mark.asyncio
async def test_t10_get_not_found(api_client, auth_headers):
    pid = uuid.uuid4()
    resp = await api_client.get(f"/api/v1/payments/{pid}", headers=auth_headers)
    assert resp.status_code == 404
