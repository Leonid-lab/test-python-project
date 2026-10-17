import uuid

import pytest

from app.gateway.simulator import deterministic_outcome, set_gateway_test_hooks
from app.models.payment import PaymentStatus

pytestmark = pytest.mark.unit


class _Force:
    def __init__(self, status: str):
        self._status = status

    def get_outcome(self, payment_id: uuid.UUID) -> str | None:
        return self._status


def test_deterministic_outcome_forced():
    pid = uuid.uuid4()
    set_gateway_test_hooks(None, _Force(PaymentStatus.failed.value))
    assert deterministic_outcome(pid) == PaymentStatus.failed.value
    set_gateway_test_hooks(None, None)


def test_deterministic_distribution():
    set_gateway_test_hooks(None, None)
    outcomes = {deterministic_outcome(uuid.uuid4()) for _ in range(200)}
    assert PaymentStatus.succeeded.value in outcomes
    assert PaymentStatus.failed.value in outcomes
