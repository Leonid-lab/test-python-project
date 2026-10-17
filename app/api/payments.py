from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import parse_idempotency_key, verify_api_key
from app.config import get_settings
from app.db import get_db_session
from app.schemas.payments import (
    CreatePaymentRequest,
    CreatePaymentResponse,
    Currency,
    PaymentDetailResponse,
    PaymentStatus,
    WebhookStatus,
)
from app.services.payments import (
    IdempotencyConflictError,
    create_payment,
    get_payment_by_id,
)
from app.services.request_hash import normalize_amount
from app.webhook.ssrf import WebhookUrlError, validate_webhook_url_for_create

router = APIRouter(prefix="/api/v1/payments", tags=["payments"])


def _payment_to_detail(payment) -> PaymentDetailResponse:
    return PaymentDetailResponse(
        payment_id=payment.id,
        amount=normalize_amount(payment.amount),
        currency=Currency(payment.currency),
        description=payment.description,
        metadata=payment.payment_metadata,
        status=PaymentStatus(payment.status),
        webhook_url=payment.webhook_url,
        created_at=payment.created_at,
        processed_at=payment.processed_at,
        webhook_status=WebhookStatus(payment.webhook_status),
        webhook_attempts=payment.webhook_attempts,
        webhook_delivered_at=payment.webhook_delivered_at,
        webhook_last_error=payment.webhook_last_error,
    )


@router.post(
    "",
    response_model=CreatePaymentResponse,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(verify_api_key)],
)
async def post_payment(
    body: CreatePaymentRequest,
    idempotency_key: str = Depends(parse_idempotency_key),
    session: AsyncSession = Depends(get_db_session),
) -> CreatePaymentResponse:
    settings = get_settings()
    try:
        validate_webhook_url_for_create(body.webhook_url, settings)
    except WebhookUrlError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e),
        ) from e

    try:
        result = await create_payment(
            session,
            amount=body.amount,
            currency=body.currency.value,
            description=body.description,
            metadata=body.metadata,
            webhook_url=body.webhook_url,
            idempotency_key=idempotency_key,
        )
    except IdempotencyConflictError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Idempotency key reused with different payload",
        ) from None

    payment = result.payment
    return CreatePaymentResponse(
        payment_id=payment.id,
        status=PaymentStatus(payment.status),
        created_at=payment.created_at,
    )


@router.get(
    "/{payment_id}",
    response_model=PaymentDetailResponse,
    dependencies=[Depends(verify_api_key)],
)
async def get_payment(
    payment_id: UUID,
    session: AsyncSession = Depends(get_db_session),
) -> PaymentDetailResponse:
    payment = await get_payment_by_id(session, payment_id)
    if payment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Payment not found")
    return _payment_to_detail(payment)
