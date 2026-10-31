# `tools/sales.py` — explained

**What it is:** the analytical core of the whole project — the tools
behind Workflow A ("why did sales drop?") and the margin-impact check in
Workflow D. Every formula here comes from `metrics.py`; this file applies
those definitions, it doesn't invent its own.

## `_summary_for_window(conn, window)` — the shared engine

A private helper that every other function in this file calls at least
once. Given one date window, it runs four queries:

1. Completed orders + their total revenue.
2. Cancelled orders (counted, but never added to revenue).
3. Refunds issued *within* the window (by `refund_date`, not the
   original sale date — see `metrics.py`'s refund-timing rule).
4. Margin: `SUM((unit_price - cost) * quantity)` across completed-order
   line items.

Centralizing this in one helper is deliberate: `get_sales_summary` and
`compare_sales_periods` both call it, so the two tools can never
accidentally disagree about what "revenue" means for the same window —
if they each ran their own slightly different query, a drift bug would
be almost invisible until someone compared the two numbers by hand.

## `get_sales_summary(start_date, end_date)`

The brief's "orders, revenue, AOV, refunds for dates" tool. Thin wrapper:
validate the dates, call the shared helper, return its result.

## `compare_sales_periods(current_*, previous_*)`

Takes two **explicit** date ranges (not "last week" as a string — Workflow
A's relative language gets turned into concrete dates by
`metrics.last_n_complete_days` / `previous_n_complete_days` *before* this
tool is ever called, so there's no ambiguity at the database layer about
what "the current period" means). Runs the shared helper twice and
returns both summaries plus the deltas: `revenue_change`,
`revenue_change_pct`, `order_count_change`, `margin_pct_change`.

## `get_product_performance(start_date, end_date, sort_by, limit)`

Ranks products by revenue, units sold, or margin over a window. This is
the tool that answers "which products contributed most" — call it once
for the current window and once for the previous window, then diff the
two result sets (done in `app/mock_agent.py` / left to the model's own
reasoning in `app/agent.py`) to see each product's contribution to a
change. `sort_by` is validated against an explicit allowlist of three
values; anything else raises `ToolValidationError` rather than silently
falling back to a default sort order the caller didn't ask for.

## `get_refund_summary(start_date, end_date, category=None, reason=None)`

Groups refunds by category and reason, and — importantly — computes each
category's `refund_rate_vs_orders` (refunds ÷ orders in that category
*and* window), not just a raw refund count. A raw count would make a big
category look "bad" just for being big; the rate is what actually answers
"is this category unusually refund-prone." This is the tool
`docs/data_profile.md` #2 uses to confirm `General Merchandise` has a
real, measurable refund-rate spike in the UCI data.

## How this connects to the rest of the project

`app/mock_agent.py`'s Workflow A handler calls `compare_sales_periods`,
`get_product_performance` (twice — current and previous window), and
`get_refund_summary` in sequence — exactly the brief's described
investigation steps. `tests/test_tools.py` checks these functions
against the real, documented patterns in `docs/data_profile.md`.
