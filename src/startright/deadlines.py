import calendar
from datetime import date


def due_date_next_month(period_end: date, day_of_month: int) -> date:
    """Return the given day in the month after period_end.

    If that month is shorter (e.g. day 31 in February), use its last day.
    """
    if not 1 <= day_of_month <= 31:
        raise ValueError("day_of_month must be between 1 and 31")
    year = period_end.year + (period_end.month // 12)
    month = period_end.month % 12 + 1
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, min(day_of_month, last_day))


def days_until(deadline: date, today: date) -> int:
    """Days from today until the deadline (negative if it has passed)."""
    return (deadline - today).days