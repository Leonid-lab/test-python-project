import pytest
from decimal import Decimal
from pydantic import ValidationError

from app.schemas.payments import CreatePaymentRequest

pytestmark = pytest.mark.unit


def test_amount_rejects_extra_precision():
    with pytest.raises(ValidationError):
        CreatePaymentRequest(
            amount="1.001",
            currency="RUB",
            description="x",
            webhook_url="https://example.org/h",
        )


def test_amount_accepts_string_and_number():
    r1 = CreatePaymentRequest(
        amount="10.50",
        currency="USD",
        description="x",
        webhook_url="https://example.org/h",
    )
    r2 = CreatePaymentRequest(
        amount=10.5,
        currency="USD",
        description="x",
        webhook_url="https://example.org/h",
    )
    assert r1.amount == r2.amount == Decimal("10.50")
