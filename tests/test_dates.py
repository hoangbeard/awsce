from datetime import date

import pytest

from awsce.dates import DateRangeError, months_back, resolve_period


def test_default_is_current_month_so_far():
    assert resolve_period(None, None, today=date(2026, 3, 15)) == ("2026-03-01", "2026-03-15")


def test_first_of_month_defaults_to_previous_month():
    assert resolve_period(None, None, today=date(2026, 3, 1)) == ("2026-02-01", "2026-03-01")


def test_explicit_dates():
    assert resolve_period("2026-01-01", "2026-02-01") == ("2026-01-01", "2026-02-01")


@pytest.mark.parametrize(
    ("start", "end"), [("2026-02-01", "2026-02-01"), ("2026-03-01", "2026-02-01")]
)
def test_end_must_be_after_start(start, end):
    with pytest.raises(DateRangeError, match="exclusive"):
        resolve_period(start, end)


def test_bad_format():
    with pytest.raises(DateRangeError, match="YYYY-MM-DD"):
        resolve_period("01/02/2026", None)


def test_months_back():
    assert months_back(2, today=date(2026, 3, 15)) == ("2026-01-01", "2026-03-15")
    assert months_back(1, today=date(2026, 3, 1)) == ("2026-02-01", "2026-03-02")
