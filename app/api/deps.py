import hmac
import re

from fastapi import Header, HTTPException, status

from app.config import get_settings

_IDEMPOTENCY_PATTERN = re.compile(r"^[^\x00-\x1f\x7f]+$")


async def verify_api_key(x_api_key: str | None = Header(default=None, alias="X-API-Key")) -> None:
    if not x_api_key:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")
    expected = get_settings().api_key
    if not hmac.compare_digest(x_api_key, expected):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")


def parse_idempotency_key(
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> str:
    if idempotency_key is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Idempotency-Key header is required",
        )
    if idempotency_key != idempotency_key.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid Idempotency-Key",
        )
    key = idempotency_key.strip()
    if not key or len(key) > 255:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid Idempotency-Key",
        )
    if not _IDEMPOTENCY_PATTERN.match(key):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid Idempotency-Key",
        )
    return key
