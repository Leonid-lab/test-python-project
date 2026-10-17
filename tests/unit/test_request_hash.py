import pytest
from decimal import Decimal

from app.services.request_hash import compute_request_hash, normalize_amount

pytestmark = pytest.mark.unit


def test_normalize_amount():
    assert normalize_amount(Decimal("1250.5")) == "1250.50"


def test_request_hash_stable():
    h1 = compute_request_hash(
        Decimal("10.00"), "RUB", "desc", {"a": 1}, "https://example.org/h"
    )
    h2 = compute_request_hash(
        Decimal("10"), "RUB", "desc", {"a": 1}, "https://example.org/h"
    )
    assert h1 == h2
