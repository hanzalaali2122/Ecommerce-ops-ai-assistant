"""
metrics.py
--------------------------------------------------------------------------
WHAT THIS FILE IS FOR
The project brief explicitly says: "Define metrics before building tools.
Document the reporting timezone, date boundaries, included order statuses,
discount treatment, refund timing, currency conversion policy, and revenue
and margin formulas. Use these definitions consistently across every tool."

This file IS that documentation, written as both comments and real Python
constants/functions, so tools can't quietly drift from the definitions --
they have to import them. If a definition changes, it changes in one place
and every tool that depends on it changes with it.

Nothing in here touches the database. It's pure business logic and date
math, which makes it easy to unit test on its own (see tests/test_metrics.py).
--------------------------------------------------------------------------
DEFINITIONS
--------------------------------------------------------------------------
1. REPORTING TIMEZONE
   All dates in the database are stored as naive ISO-8601 strings
   ("YYYY-MM-DD HH:MM:SS") already normalized to the store's own reporting
   timezone, which we define as UTC. We do NOT attempt to convert per
   customer or per country -- Shopify-style reporting is normally done in
   one fixed "shop timezone", and we use UTC as that fixed point. If this
   were wired to a real store, the loader (database/build_database.py)
   would be the one place that converts incoming timestamps into this
   reporting timezone.

2. DATE BOUNDARIES ("last 7 days", "last week", etc.)
   A "day" boundary is always a *complete calendar day* in the reporting
   timezone: 00:00:00 up to (but not including) the next day's 00:00:00.
   "The last N complete days" means: take "today" (the reporting
   timezone's current date), drop today itself (it's not complete yet),
   and count backward N days from yesterday. This matches Workflow A's
   wording exactly: "Compare the last seven complete days with the
   previous seven."

   Example, if today is 2026-10-21:
     last 7 complete days  = 2026-10-14 .. 2026-10-20 (inclusive)
     previous 7 days       = 2026-10-07 .. 2026-10-13 (inclusive)

3. INCLUDED ORDER STATUSES
   orders.status is either 'completed' or 'cancelled'.
   - Revenue, AOV, and product-performance metrics count 'completed'
     orders only.
   - 'cancelled' orders are excluded from revenue entirely (their value
     was never realized) but ARE counted separately as a signal of
     operational problems (see get_sales_summary's `cancelled_orders`
     field and Workflow A step 3, "examine refunds where relevant").
   - We do NOT have a 'pending'/'processing' status in this dataset
     (UCI's data is historical, not live), but the field exists so a
     live-sync version of this system can add those statuses without a
     schema change. Any status other than 'completed' is excluded from
     revenue by default.

4. DISCOUNT TREATMENT
   order_items.discount is a per-line discount *amount* already baked
   into unit_price (i.e. unit_price is the price the customer actually
   paid, after discount). orders.subtotal is the sum of
   (quantity * full undiscounted price) and orders.discount_total is the
   sum of all line discounts, so:
       orders.total = orders.subtotal - orders.discount_total
   Revenue calculations always use orders.total (post-discount), because
   that is what the business actually collected. Margin calculations use
   the discounted unit_price against variants.cost, so a discount that
   cuts margin shows up correctly as lower margin, not hidden revenue.

5. REFUND TIMING
   A refund is attributed to the date it was *issued* (refunds.refund_date),
   not the date of the original order. This matches how a real store's
   books work: a refund processed today reduces today's net figures even
   if the sale happened last month. get_refund_summary always filters on
   refunds.refund_date, and get_sales_summary's `net_revenue` subtracts
   refunds issued *within the requested window*, regardless of when the
   original sale happened.

6. CURRENCY CONVERSION POLICY
   All amounts in the database are stored in the store's home currency,
   GBP (matching the real UCI dataset, which is a UK retailer). We do NOT
   convert stored values. get_exchange_rate is a separate, explicit tool
   that fetches a reference rate for display purposes only (e.g. "what is
   that in USD right now") -- it never mutates stored figures, and a
   fetched rate is treated as a point-in-time reference, not a live feed
   that changes the meaning of past data.

7. REVENUE FORMULA
       revenue(window) = SUM(orders.total) for orders.status = 'completed'
                          AND orders.order_date within window
       net_revenue(window) = revenue(window) - SUM(refunds.amount)
                              for refunds.refund_date within window

8. MARGIN FORMULA
       line_margin = (unit_price - variants.cost) * quantity
       margin(window) = SUM(line_margin) over order_items joined to
                         orders.status = 'completed' orders in window
       margin_pct(window) = margin(window) / revenue(window)   (0 if revenue is 0)

9. AVERAGE ORDER VALUE (AOV)
       AOV(window) = revenue(window) / count(completed orders in window)
       (0 if there are no completed orders -- never divide by zero)

--------------------------------------------------------------------------
"""

from datetime import date, datetime, timedelta
from dataclasses import dataclass

REPORTING_TIMEZONE = "UTC"
INCLUDED_REVENUE_STATUSES = ("completed",)
HOME_CURRENCY = "GBP"


@dataclass(frozen=True)
class DateWindow:
    """An inclusive [start_date, end_date] window of complete calendar days."""
    start_date: date
    end_date: date

    def as_sql_bounds(self):
        """
        Returns (start_str, end_exclusive_str) ready to drop into a SQL
        WHERE clause as: order_date >= start_str AND order_date < end_exclusive_str
        The end bound is exclusive (start of the day AFTER end_date) so
        timestamps anywhere during end_date are correctly included.
        """
        start_str = self.start_date.isoformat() + " 00:00:00"
        end_exclusive = (self.end_date + timedelta(days=1)).isoformat() + " 00:00:00"
        return start_str, end_exclusive

    def days(self) -> int:
        return (self.end_date - self.start_date).days + 1


def last_n_complete_days(n: int, today: date | None = None) -> DateWindow:
    """
    The last `n` *complete* calendar days, not counting today (today isn't
    over yet, so it can't be a complete day). If today is 2026-10-21 and
    n=7, this returns 2026-10-14 .. 2026-10-20.
    """
    if today is None:
        today = date.today()
    end_date = today - timedelta(days=1)
    start_date = end_date - timedelta(days=n - 1)
    return DateWindow(start_date, end_date)


def previous_n_complete_days(n: int, today: date | None = None) -> DateWindow:
    """
    The N complete days immediately before `last_n_complete_days(n)`.
    Used as the comparison baseline in Workflow A (week-over-week style
    comparisons), so a 7-vs-7 comparison always lines up weekday-for-weekday
    when n is a multiple of 7.
    """
    current = last_n_complete_days(n, today)
    end_date = current.start_date - timedelta(days=1)
    start_date = end_date - timedelta(days=n - 1)
    return DateWindow(start_date, end_date)


def parse_window(start: str, end: str) -> DateWindow:
    """Parse two 'YYYY-MM-DD' strings into a validated DateWindow."""
    start_date = datetime.strptime(start, "%Y-%m-%d").date()
    end_date = datetime.strptime(end, "%Y-%m-%d").date()
    if end_date < start_date:
        raise ValueError(f"end date {end} is before start date {start}")
    return DateWindow(start_date, end_date)


def safe_divide(numerator: float, denominator: float) -> float:
    """Division that returns 0.0 instead of raising on a zero denominator.
    Used everywhere a metric could otherwise divide by zero orders/units
    (see the brief's 'Zero sales -> avoid division by zero' test case)."""
    if not denominator:
        return 0.0
    return numerator / denominator


def round_money(value: float) -> float:
    """Round a currency amount to 2 decimal places, consistently."""
    return round(value + 1e-9, 2)
