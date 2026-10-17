import hashlib
import json
from decimal import Decimal


def normalize_amount(amount: Decimal) -> str:
    normalized = amount.quantize(Decimal("0.01"))
    return format(normalized, "f")


def compute_request_hash(
    amount: Decimal,
    currency: str,
    description: str,
    metadata: dict,
    webhook_url: str,
) -> str:
    canonical = "|".join(
        [
            normalize_amount(amount),
            currency.upper(),
            description,
            json.dumps(metadata, sort_keys=True, separators=(",", ":")),
            webhook_url,
        ]
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
