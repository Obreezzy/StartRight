from decimal import Decimal

import pytest

from startright.fees import FeeItem, percentage_contribution, total_fees


def test_total_fees_adds_items():
    items = [FeeItem("Name search", Decimal("50")), FeeItem("Filing", Decimal("25.50"))]
    assert total_fees(items) == Decimal("75.50")


def test_total_fees_empty_list_is_zero():
    assert total_fees([]) == Decimal("0")


def test_total_fees_rejects_mixed_currencies():
    items = [FeeItem("A", Decimal("10"), "USD"), FeeItem("B", Decimal("10"), "ZWG")]
    with pytest.raises(ValueError):
        total_fees(items)


def test_total_fees_rejects_negative_amounts():
    with pytest.raises(ValueError):
        total_fees([FeeItem("Bad", Decimal("-5"))])


def test_percentage_contribution_basic():
    assert percentage_contribution(Decimal("1000"), Decimal("3.5")) == Decimal("35.00")


def test_percentage_contribution_rounds_half_up():
    # 33.33 * 3.5 / 100 = 1.16655, which rounds to 1.17
    assert percentage_contribution(Decimal("33.33"), Decimal("3.5")) == Decimal("1.17")


def test_percentage_contribution_rejects_negative_values():
    with pytest.raises(ValueError):
        percentage_contribution(Decimal("-1"), Decimal("3.5"))