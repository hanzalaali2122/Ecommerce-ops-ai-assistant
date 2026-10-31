"""
tests/test_metrics.py
--------------------------------------------------------------------------
Unit tests for metrics.py -- the date-window math and safe-division
helpers that every tool depends on. These are written in plain pytest
style (`def test_...(): assert ...`) so they run with a normal
`pytest tests/` once you have pytest installed.

They were originally verified in this sandbox (which has no internet
access to pip-install pytest) using tests/run_tests.py, a zero-dependency
runner included alongside this file -- see that file's docstring.
"""

from datetime import date
from metrics import (
    last_n_complete_days, previous_n_complete_days, parse_window,
    safe_divide, round_money, DateWindow,
)


def test_last_n_complete_days_excludes_today():
    window = last_n_complete_days(7, today=date(2026, 10, 21))
    assert window.start_date == date(2026, 10, 14)
    assert window.end_date == date(2026, 10, 20)
    assert window.days() == 7


def test_previous_n_complete_days_is_immediately_before_current():
    today = date(2026, 10, 21)
    current = last_n_complete_days(7, today=today)
    previous = previous_n_complete_days(7, today=today)
    assert previous.end_date == current.start_date - __import__("datetime").timedelta(days=1)
    assert previous.days() == 7


def test_date_window_sql_bounds_are_half_open():
    window = DateWindow(date(2026, 9, 1), date(2026, 9, 8))
    start_str, end_exclusive = window.as_sql_bounds()
    assert start_str == "2026-09-01 00:00:00"
    # end bound is the day AFTER end_date, so timestamps during end_date match "< end_exclusive"
    assert end_exclusive == "2026-09-09 00:00:00"


def test_parse_window_rejects_end_before_start():
    try:
        parse_window("2026-09-10", "2026-09-01")
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_safe_divide_handles_zero_denominator():
    assert safe_divide(100, 0) == 0.0
    assert safe_divide(0, 0) == 0.0
    assert safe_divide(10, 4) == 2.5


def test_round_money():
    assert round_money(1.005) == 1.0 or round_money(1.005) == 1.01  # float rounding edge case, both acceptable
    assert round_money(19.999) == 20.0
