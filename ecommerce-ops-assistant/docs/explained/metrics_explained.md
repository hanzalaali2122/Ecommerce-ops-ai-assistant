# `metrics.py` — explained

**What it is:** the project's one and only definition of what words like
"revenue," "margin," and "last week" mean. The brief is explicit about
this: *"Define metrics before building tools... use these definitions
consistently across every tool."* This file is that definition, written
as real code (not just a comment), so every tool is forced to import it
rather than quietly redefining "revenue" its own way.

## The nine things it pins down

1. **Reporting timezone** — fixed at UTC, store-wide (no per-customer
   timezone conversion, matching how a real Shopify store reports).
2. **Date boundaries** — a "complete day" means 00:00:00 up to (but not
   including) the next day. "Last 7 complete days" excludes *today*,
   because today isn't over yet.
3. **Included order statuses** — only `'completed'` orders count toward
   revenue. `'cancelled'` orders are tracked separately (as a signal of
   operational problems) but never counted as revenue.
4. **Discount treatment** — `unit_price` is already the post-discount
   price the customer paid; `orders.total = orders.subtotal -
   orders.discount_total`. Revenue uses `orders.total`; margin uses the
   discounted price against cost, so a discount that cuts margin shows up
   as lower margin, not hidden revenue.
5. **Refund timing** — a refund counts against the date it was *issued*,
   not the date of the original sale (matching how real bookkeeping
   works).
6. **Currency policy** — everything is stored in GBP (the real UCI data's
   home currency). `get_exchange_rate` never converts stored figures; a
   fetched rate is a point-in-time reference for display only.
7. **Revenue formula** —
   `SUM(orders.total)` for completed orders in the window.
8. **Margin formula** —
   `SUM((unit_price - cost) * quantity)` for completed-order line items.
9. **AOV formula** — `revenue / completed order count`, with a hard rule:
   **never divide by zero**.

## The code, piece by piece

- **`DateWindow`** — a small, immutable (`frozen=True`) object holding a
  start and end date. Its `as_sql_bounds()` method is the one place that
  turns "inclusive end date" into the half-open SQL range
  (`>= start AND < end+1day`) every tool actually queries with — get this
  wrong once, forget it everywhere else, and you'd silently drop or
  double-count the last day's orders depending on which way you got it
  wrong. Centralizing it means that bug class can't happen per-tool.
- **`last_n_complete_days` / `previous_n_complete_days`** — the exact
  date math Workflow A needs ("the last seven complete days vs. the
  previous seven"), independently testable (see `tests/test_metrics.py`)
  without touching the database at all.
- **`safe_divide`** — returns `0.0` instead of raising on a zero
  denominator. Every AOV/margin-percentage calculation in the project
  routes through this, which is what satisfies the brief's "Zero sales →
  avoid division by zero" test case everywhere at once, rather than
  needing a defensive `if` in every tool.
- **`round_money`** — rounds to 2 decimal places consistently (with a
  tiny epsilon nudge to dodge float-rounding surprises like
  `round(1.005, 2) == 1.0` instead of `1.01`).

## Why this file has no database code at all

That's deliberate. Pure business-logic and date math is trivial to unit
test in isolation (`tests/test_metrics.py` does exactly that, with zero
setup, no database connection needed). Every tool in `tools/*.py` imports
from here rather than reimplementing any of it.
