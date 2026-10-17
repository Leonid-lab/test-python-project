"""T26: SSRF policy in strict (production-like) settings."""

import pytest

from app.config import Settings
from app.webhook.client import WebhookDeliveryError, post_webhook
from app.webhook.ssrf import WebhookUrlError, validate_webhook_url_for_create

pytestmark = pytest.mark.unit


def _strict_settings(**overrides) -> Settings:
    base = {
        "api_key": "x" * 16,
        "database_url": "postgresql+asyncpg://u:p@localhost/db",
        "rabbitmq_url": "amqp://localhost",
        "webhook_allowed_hosts": "example.org",
        "webhook_ssrf_relaxed": False,
        "webhook_allow_http": False,
    }
    base.update(overrides)
    return Settings(**base)


def test_t26_create_rejects_non_allowlist_host():
    settings = _strict_settings()
    with pytest.raises(WebhookUrlError):
        validate_webhook_url_for_create("https://evil.com/hook", settings)


def test_t26_create_rejects_http_by_default():
    settings = _strict_settings(webhook_allowed_hosts="example.org")
    with pytest.raises(WebhookUrlError):
        validate_webhook_url_for_create("http://example.org/hook", settings)


def test_t26_subdomain_not_in_allowlist():
    settings = _strict_settings(webhook_allowed_hosts="example.org")
    with pytest.raises(WebhookUrlError):
        validate_webhook_url_for_create("https://api.example.org/hook", settings)


@pytest.mark.asyncio
async def test_t26_delivery_blocks_private_resolution(monkeypatch):
    import asyncio

    settings = _strict_settings(webhook_allowed_hosts="example.org")

    async def fake_getaddrinfo(host, port, *args, **kwargs):
        return [(2, 1, 6, "", ("10.0.0.5", port))]

    loop = asyncio.get_running_loop()
    monkeypatch.setattr(loop, "getaddrinfo", fake_getaddrinfo)
    with pytest.raises(WebhookDeliveryError) as exc:
        await post_webhook(
            "https://example.org/hook",
            {"x": 1},
            event_id="e1",
            settings=settings,
        )
    assert exc.value.retryable is False
