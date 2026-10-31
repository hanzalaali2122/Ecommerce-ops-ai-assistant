"""
tools/validation.py
--------------------------------------------------------------------------
The brief's "Required controls" table says every tool must validate "IDs,
date ranges, currencies, quantities, and result sizes" and must "use
predefined functions and parameterized SQL" -- never build raw SQL out of
string concatenation.

This file centralizes those checks so each tool function stays short and
so the rules are consistent everywhere (a date range validated one way in
get_sales_summary and a different way in compare_sales_periods would be a
bug waiting to happen).

Every function here either returns a cleaned-up value or raises
ToolValidationError with a message written for a human (or the model) to
read -- app/agent.py catches this error type and turns it into a
structured "error" tool result instead of letting the whole request crash.
"""

from datetime import date, datetime

MAX_RESULT_ROWS = 200          # hard cap on rows any tool will ever return
MAX_DATE_RANGE_DAYS = 366       # a little over a year; the dataset itself only spans ~1 year
SUPPORTED_CURRENCIES = {"GBP", "USD", "EUR"}


class ToolValidationError(ValueError):
    """Raised when a tool's arguments fail validation. Always has a plain-
    English message safe to show directly to the model or the person."""


def require_non_empty_string(value, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ToolValidationError(f"'{field_name}' must be a non-empty string.")
    return value.strip()


def validate_date_string(value, field_name: str) -> date:
    if not isinstance(value, str):
        raise ToolValidationError(f"'{field_name}' must be a date string like 'YYYY-MM-DD'.")
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        raise ToolValidationError(
            f"'{field_name}' = {value!r} is not a valid date in 'YYYY-MM-DD' format."
        )


def validate_date_range(start: str, end: str):
    start_d = validate_date_string(start, "start_date")
    end_d = validate_date_string(end, "end_date")
    if end_d < start_d:
        raise ToolValidationError(
            f"end_date ({end}) is before start_date ({start})."
        )
    span = (end_d - start_d).days
    if span > MAX_DATE_RANGE_DAYS:
        raise ToolValidationError(
            f"Date range of {span} days exceeds the maximum of {MAX_DATE_RANGE_DAYS} days. "
            f"Narrow the range and ask again."
        )
    return start_d, end_d


def validate_positive_int(value, field_name: str, max_value: int | None = None) -> int:
    try:
        ivalue = int(value)
    except (TypeError, ValueError):
        raise ToolValidationError(f"'{field_name}' must be a whole number.")
    if ivalue <= 0:
        raise ToolValidationError(f"'{field_name}' must be greater than zero.")
    if max_value is not None and ivalue > max_value:
        raise ToolValidationError(f"'{field_name}' cannot exceed {max_value}.")
    return ivalue


def validate_limit(value, default: int = 20) -> int:
    """A 'limit' (how many rows to return) is optional; validate it if given,
    otherwise fall back to a sane default, and always cap it at MAX_RESULT_ROWS."""
    if value is None:
        return default
    limit = validate_positive_int(value, "limit", max_value=MAX_RESULT_ROWS)
    return limit


def validate_currency(value: str) -> str:
    code = require_non_empty_string(value, "currency").upper()
    if code not in SUPPORTED_CURRENCIES:
        raise ToolValidationError(
            f"Unsupported currency {code!r}. Supported: {sorted(SUPPORTED_CURRENCIES)}."
        )
    return code


def validate_percentage(value, field_name: str = "percentage") -> float:
    try:
        pct = float(value)
    except (TypeError, ValueError):
        raise ToolValidationError(f"'{field_name}' must be a number.")
    if not (0 < pct <= 90):
        raise ToolValidationError(
            f"'{field_name}' must be between 0 and 90 (got {pct}). "
            f"Discounts above 90% are blocked as almost certainly a mistake."
        )
    return pct
