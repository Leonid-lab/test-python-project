from datetime import datetime
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

MAX_METADATA_BYTES = 16 * 1024


class Currency(str, Enum):
    RUB = "RUB"
    USD = "USD"
    EUR = "EUR"


class PaymentStatus(str, Enum):
    pending = "pending"
    succeeded = "succeeded"
    failed = "failed"


class WebhookStatus(str, Enum):
    pending = "pending"
    delivered = "delivered"
    exhausted = "exhausted"


class CreatePaymentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    amount: Decimal
    currency: Currency
    description: str = Field(min_length=1, max_length=500)
    metadata: dict[str, Any] = Field(default_factory=dict)
    webhook_url: str = Field(min_length=1, max_length=2048)

    @field_validator("amount", mode="before")
    @classmethod
    def parse_amount(cls, v: Any) -> Decimal:
        if isinstance(v, bool):
            raise ValueError("invalid amount")
        try:
            if isinstance(v, int | float):
                dec = Decimal(str(v))
            else:
                dec = Decimal(str(v))
        except (InvalidOperation, ValueError) as e:
            raise ValueError("invalid amount") from e
        return dec

    @field_validator("amount")
    @classmethod
    def validate_amount(cls, v: Decimal) -> Decimal:
        if not v.is_finite():
            raise ValueError("amount must be finite")
        if v <= 0:
            raise ValueError("amount must be positive")
        if v.as_tuple().exponent < -2:
            raise ValueError("amount precision exceeds 2 decimal places")
        max_val = Decimal("9999999999999999.99")
        if v > max_val:
            raise ValueError("amount too large")
        return v.quantize(Decimal("0.01"))

    @field_validator("metadata")
    @classmethod
    def validate_metadata_size(cls, v: dict[str, Any]) -> dict[str, Any]:
        import json

        if len(json.dumps(v, separators=(",", ":")).encode()) > MAX_METADATA_BYTES:
            raise ValueError("metadata too large")
        return v


class CreatePaymentResponse(BaseModel):
    payment_id: UUID
    status: PaymentStatus
    created_at: datetime


class PaymentDetailResponse(BaseModel):
    payment_id: UUID
    amount: str
    currency: Currency
    description: str
    metadata: dict[str, Any]
    status: PaymentStatus
    webhook_url: str
    created_at: datetime
    processed_at: datetime | None
    webhook_status: WebhookStatus
    webhook_attempts: int
    webhook_delivered_at: datetime | None
    webhook_last_error: str | None
