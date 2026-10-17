import ipaddress
import re
from urllib.parse import urlparse

from app.config import Settings

_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")


class WebhookUrlError(ValueError):
    pass


def _normalize_host(host: str) -> str:
    host = host.strip().lower()
    if host.startswith("[") and host.endswith("]"):
        host = host[1:-1]
    return host


def validate_webhook_url_for_create(url: str, settings: Settings) -> str:
    if len(url) > 2048:
        raise WebhookUrlError("webhook_url too long")
    if _CONTROL_CHARS.search(url):
        raise WebhookUrlError("webhook_url contains control characters")

    parsed = urlparse(url)
    if parsed.scheme == "https":
        pass
    elif parsed.scheme == "http" and settings.webhook_allow_http:
        pass
    else:
        raise WebhookUrlError("webhook_url must use https")

    if parsed.username or parsed.password:
        raise WebhookUrlError("webhook_url must not contain userinfo")

    host = _normalize_host(parsed.hostname or "")
    if not host:
        raise WebhookUrlError("webhook_url host is required")

    port = parsed.port
    if port is None:
        port = 443 if parsed.scheme == "https" else 80
    if port not in (80, 443, 8080, 8443):
        raise WebhookUrlError("webhook_url port not allowed")

    allowed = settings.allowed_webhook_hosts()
    if not allowed:
        raise WebhookUrlError("webhook host not in allowlist")
    if host not in allowed:
        raise WebhookUrlError("webhook host not in allowlist")

    return url


def is_blocked_ip(ip_str: str) -> bool:
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return True
    if ip.is_loopback or ip.is_private or ip.is_link_local:
        return True
    if ip.is_multicast or ip.is_reserved or ip.is_unspecified:
        return True
    if ip == ipaddress.ip_address("169.254.169.254"):
        return True
    return False
