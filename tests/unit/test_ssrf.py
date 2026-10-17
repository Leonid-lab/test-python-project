import pytest

from app.config import Settings
from app.webhook.ssrf import WebhookUrlError, is_blocked_ip, validate_webhook_url_for_create

pytestmark = pytest.mark.unit


def test_block_private_ip():
    assert is_blocked_ip("10.0.0.1")
    assert is_blocked_ip("127.0.0.1")
    assert is_blocked_ip("169.254.169.254")


def test_allowlist_exact_host():
    settings = Settings(
        api_key="x" * 8,
        database_url="postgresql+asyncpg://u:p@localhost/db",
        rabbitmq_url="amqp://localhost",
        webhook_allowed_hosts="example.org",
    )
    validate_webhook_url_for_create("https://example.org/path", settings)
    with pytest.raises(WebhookUrlError):
        validate_webhook_url_for_create("https://evil.example.org/path", settings)
