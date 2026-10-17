import uuid

import pytest

pytestmark = pytest.mark.unit


@pytest.mark.asyncio
async def test_t02_get_payment(api_client, auth_headers, payment_payload):
    headers = {**auth_headers, "Idempotency-Key": "t02-get"}
    created = await api_client.post("/api/v1/payments", json=payment_payload, headers=headers)
    assert created.status_code == 202
    pid = created.json()["payment_id"]
    got = await api_client.get(f"/api/v1/payments/{pid}", headers=auth_headers)
    assert got.status_code == 200
    body = got.json()
    assert body["payment_id"] == pid
    assert body["status"] == "pending"
    assert body["amount"] == payment_payload["amount"]


@pytest.mark.asyncio
async def test_t03_get_unauthorized(api_client):
    pid = uuid.uuid4()
    resp = await api_client.get(f"/api/v1/payments/{pid}")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_t03_wrong_api_key(api_client, auth_headers, payment_payload):
    headers = {
        **auth_headers,
        "X-API-Key": "wrong-key-xxxxxxxx",
        "Idempotency-Key": "t03-wrong",
    }
    resp = await api_client.post("/api/v1/payments", json=payment_payload, headers=headers)
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_t09_invalid_currency_and_url(api_client, auth_headers, payment_payload):
    headers = {**auth_headers, "Idempotency-Key": "t09-currency"}
    bad_currency = {**payment_payload, "currency": "GBP"}
    r1 = await api_client.post("/api/v1/payments", json=bad_currency, headers=headers)
    assert r1.status_code == 422

    headers2 = {**auth_headers, "Idempotency-Key": "t09-url"}
    bad_url = {**payment_payload, "webhook_url": "not-a-url"}
    r2 = await api_client.post("/api/v1/payments", json=bad_url, headers=headers2)
    assert r2.status_code == 422


@pytest.mark.asyncio
async def test_t10_invalid_uuid_get(api_client, auth_headers):
    resp = await api_client.get("/api/v1/payments/not-a-uuid", headers=auth_headers)
    assert resp.status_code == 422
