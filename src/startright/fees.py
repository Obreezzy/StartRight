from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP


@dataclass(frozen=True)
class FeeItem:
    name: str
    amount: Decimal
    currency: str = "USD"


def total_fees(items: list[FeeItem]) -> Decimal:
    """Add up fees. All items must be in the same currency and non-negative."""
    if not items:
        return Decimal("0")
    if len({item.currency for item in items}) > 1:
        raise ValueError("Cannot add fees in different currencies")
    if any(item.amount < 0 for item in items):
        raise ValueError("Fees cannot be negative")
    return sum((item.amount for item in items), Decimal("0"))


def percentage_contribution(gross: Decimal, rate_percent: Decimal) -> Decimal:
    """Work out a percentage of gross pay, rounded to 2 decimal places.

    The rate is passed in, never hard-coded, because real rates must come
    from the official source documents.
    """
    if gross < 0 or rate_percent < 0:
        raise ValueError("Gross and rate must not be negative")
    result = gross * rate_percent / Decimal("100")
    return result.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)