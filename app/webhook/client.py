import asyncio
import socket
from typing import Any
from urllib.parse import urlparse

import aiohttp
from aiohttp import TCPConnector
from aiohttp.abc import AbstractResolver

from app.config import Settings
from app.webhook.ssrf import is_blocked_ip, validate_webhook_url_for_create


class WebhookDeliveryError(Exception):
    def __init__(self, message: str, *, retryable: bool = True):
        super().__init__(message)
        self.retryable = retryable


class _PinnedResolver(AbstractResolver):
    def __init__(self, host: str, pinned_ip: str):
        self._host = host
        self._pinned_ip = pinned_ip

    async def resolve(self, host, port=0, family=socket.AF_INET):
        if host.lower() != self._host.lower():
            raise WebhookDeliveryError("unexpected resolve host", retryable=False)
        return [
            {
                "hostname": host,
                "host": self._pinned_ip,
                "port": port,
                "family": family,
                "proto": socket.IPPROTO_TCP,
                "flags": socket.AI_NUMERICHOST,
            }
        ]

    async def close(self):
        pass


async def _resolve_and_pin(url: str, settings: Settings) -> tuple[str, str, int, str]:
    validate_webhook_url_for_create(url, settings)
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    port = parsed.port or (443 if parsed.scheme == "https" else 80)

    loop = asyncio.get_running_loop()
    infos = await loop.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    if not infos:
        raise WebhookDeliveryError("dns resolution failed", retryable=True)

    pinned_ip: str | None = None
    for info in infos:
        sockaddr = info[4]
        ip_str = sockaddr[0]
        if is_blocked_ip(ip_str) and not settings.webhook_ssrf_relaxed:
            continue
        pinned_ip = ip_str
        break

    if pinned_ip is None:
        raise WebhookDeliveryError("webhook destination blocked", retryable=False)

    return parsed.scheme, host, port, pinned_ip


async def post_webhook(
    url: str,
    payload: dict[str, Any],
    event_id: str,
    settings: Settings,
) -> None:
    scheme, host, port, pinned_ip = await _resolve_and_pin(url, settings)
    ssl = None if scheme == "http" else True
    resolver = _PinnedResolver(host, pinned_ip)
    connector = TCPConnector(resolver=resolver, ssl=ssl, enable_cleanup_closed=True)

    timeout = aiohttp.ClientTimeout(total=settings.webhook_timeout_sec)
    headers = {
        "Content-Type": "application/json",
        "X-Event-ID": event_id,
    }

    try:
        async with aiohttp.ClientSession(
            connector=connector,
            timeout=timeout,
            trust_env=False,
        ) as session:
            async with session.post(
                url, json=payload, headers=headers, allow_redirects=False
            ) as resp:
                body = await resp.content.read(settings.webhook_max_response_bytes + 1)
                if len(body) > settings.webhook_max_response_bytes:
                    raise WebhookDeliveryError("response too large", retryable=True)
                if 200 <= resp.status < 300:
                    return
                if 300 <= resp.status < 400:
                    raise WebhookDeliveryError(
                        f"redirect status {resp.status}", retryable=True
                    )
                raise WebhookDeliveryError(
                    f"webhook status {resp.status}", retryable=True
                )
    except asyncio.TimeoutError:
        raise WebhookDeliveryError("webhook timeout", retryable=True) from None
    except aiohttp.ClientError as e:
        raise WebhookDeliveryError("webhook connection error", retryable=True) from e
    finally:
        await connector.close()
