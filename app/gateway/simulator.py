import hashlib
import uuid
from collections.abc import Awaitable, Callable
from typing import Protocol

from app.config import get_settings
from app.models.payment import PaymentStatus

SleepFn = Callable[[float], Awaitable[None]]


class GatewayOutcomeOverride(Protocol):
    def get_outcome(self, payment_id: uuid.UUID) -> str | None: ...


_outcome_override: GatewayOutcomeOverride | None = None
_sleep_fn: SleepFn | None = None


def set_gateway_test_hooks(
    sleep_fn: SleepFn | None = None,
    outcome_override: GatewayOutcomeOverride | None = None,
) -> None:
    global _sleep_fn, _outcome_override
    _sleep_fn = sleep_fn
    _outcome_override = outcome_override


def clear_gateway_test_hooks() -> None:
    set_gateway_test_hooks(None, None)


def deterministic_outcome(payment_id: uuid.UUID) -> str:
    if _outcome_override is not None:
        forced = _outcome_override.get_outcome(payment_id)
        if forced is not None:
            return forced
    digest = hashlib.sha256(str(payment_id).encode()).hexdigest()
    bucket = int(digest[:8], 16) % 100
    if bucket < 90:
        return PaymentStatus.succeeded.value
    return PaymentStatus.failed.value


def sleep_duration_seconds(payment_id: uuid.UUID) -> float:
    settings = get_settings()
    if settings.gateway_sleep_ms is not None:
        return settings.gateway_sleep_ms / 1000.0
    digest = hashlib.sha256(f"sleep:{payment_id}".encode()).hexdigest()
    span = settings.gateway_sleep_max_sec - settings.gateway_sleep_min_sec
    if span <= 0:
        return settings.gateway_sleep_min_sec
    offset = (int(digest[:8], 16) % 1000) / 1000.0 * span
    return settings.gateway_sleep_min_sec + offset


async def emulate_gateway(payment_id: uuid.UUID) -> str:
    duration = sleep_duration_seconds(payment_id)
    if _sleep_fn is not None:
        await _sleep_fn(duration)
    else:
        import asyncio

        await asyncio.sleep(duration)
    return deterministic_outcome(payment_id)
