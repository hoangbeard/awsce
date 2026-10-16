"""Date ranges for Cost Explorer queries.

Cost Explorer treats the end date as exclusive.
"""

from __future__ import annotations

from datetime import date, timedelta


class DateRangeError(ValueError):
    """Raised when a date range cannot be used with Cost Explorer."""


def _parse(value: str, name: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise DateRangeError(f"{name} must use YYYY-MM-DD, got {value!r}") from exc


def resolve_period(
    start: str | None, end: str | None, today: date | None = None
) -> tuple[str, str]:
    """Return (start, end) as ISO strings.

    Defaults to the current month so far. On the 1st of a month, when the
    current month has no data yet, it defaults to the previous month.
    """
    today = today or date.today()
    if start is None and end is None and today.day == 1:
        last_month_end = today - timedelta(days=1)
        return last_month_end.replace(day=1).isoformat(), today.isoformat()

    start_d = _parse(start, "--start") if start else today.replace(day=1)
    end_d = _parse(end, "--end") if end else today
    if end_d <= start_d:
        raise DateRangeError(
            f"--end ({end_d}) must be after --start ({start_d}). The end date is exclusive."
        )
    return start_d.isoformat(), end_d.isoformat()


def months_back(months: int, today: date | None = None) -> tuple[str, str]:
    """Return a range covering the last ``months`` full months plus this month so far."""
    today = today or date.today()
    start = today.replace(day=1)
    for _ in range(months):
        start = (start - timedelta(days=1)).replace(day=1)
    end = today if today.day > 1 else today + timedelta(days=1)
    return start.isoformat(), end.isoformat()
