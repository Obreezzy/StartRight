from datetime import date

import pytest

from startright.deadlines import days_until, due_date_next_month


def test_due_date_is_in_following_month():
    assert due_date_next_month(date(2025, 3, 31), 25) == date(2025, 4, 25)


def test_due_date_rolls_over_the_year():
    assert due_date_next_month(date(2025, 12, 31), 25) == date(2026, 1, 25)


def test_due_date_uses_last_day_of_short_month():
    assert due_date_next_month(date(2025, 1, 31), 31) == date(2025, 2, 28)


@pytest.mark.parametrize("bad_day", [0, 32])
def test_due_date_rejects_invalid_day(bad_day):
    with pytest.raises(ValueError):
        due_date_next_month(date(2025, 3, 31), bad_day)


def test_days_until_counts_forward_and_backward():
    assert days_until(date(2025, 4, 25), date(2025, 4, 20)) == 5
    assert days_until(date(2025, 4, 25), date(2025, 4, 30)) == -5