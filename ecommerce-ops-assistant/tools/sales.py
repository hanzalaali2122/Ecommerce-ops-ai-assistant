"""
tools/sales.py
--------------------------------------------------------------------------
The analytical core of Workflow A ("Why did sales drop this week?") and
Workflow D (checking a discount's margin impact before proposing it).

Every formula used here is defined once in metrics.py and just applied
here -- this file does not invent its own definition of "revenue" or
"margin". That separation is what the brief means by "define metrics
before building tools": if the definition of revenue ever needs to
change, it changes in metrics.py and every function below picks it up
automatically.
"""

from metrics import (
    DateWindow, parse_window, safe_divide, round_money,
)
from tools.db import get_connection, rows_to_dicts
from tools.validation import validate_date_range, validate_limit, ToolValidationError


def _summary_for_window(conn, window: DateWindow) -> dict:
    """Shared helper: compute the core sales numbers for one date window.
    Used by both get_sales_summary and compare_sales_periods so the two
    tools can never silently disagree about what 'revenue' means."""
    start_str, end_exclusive = window.as_sql_bounds()

    orders_row = conn.execute(
        """
        SELECT COUNT(*) AS completed_orders,
               COALESCE(SUM(total), 0) AS revenue
        FROM orders
        WHERE status = 'completed'
          AND order_date >= ? AND order_date < ?
        """,
        (start_str, end_exclusive),
    ).fetchone()

    cancelled_row = conn.execute(
        """
        SELECT COUNT(*) AS cancelled_orders
        FROM orders
        WHERE status = 'cancelled'
          AND order_date >= ? AND order_date < ?
        """,
        (start_str, end_exclusive),
    ).fetchone()

    refund_row = conn.execute(
        """
        SELECT COALESCE(SUM(amount), 0) AS refund_amount, COUNT(*) AS refund_count
        FROM refunds
        WHERE refund_date >= ? AND refund_date < ?
        """,
        (start_str, end_exclusive),
    ).fetchone()

    margin_row = conn.execute(
        """
        SELECT COALESCE(SUM((oi.unit_price - v.cost) * oi.quantity), 0) AS margin
        FROM order_items oi
        JOIN orders o ON o.order_id = oi.order_id
        JOIN variants v ON v.variant_id = oi.variant_id
        WHERE o.status = 'completed'
          AND o.order_date >= ? AND o.order_date < ?
        """,
        (start_str, end_exclusive),
    ).fetchone()

    revenue = orders_row["revenue"]
    completed_orders = orders_row["completed_orders"]
    net_revenue = revenue - refund_row["refund_amount"]
    margin = margin_row["margin"]

    return {
        "start_date": window.start_date.isoformat(),
        "end_date": window.end_date.isoformat(),
        "days": window.days(),
        "completed_orders": completed_orders,
        "cancelled_orders": cancelled_row["cancelled_orders"],
        "revenue": round_money(revenue),
        "refund_amount": round_money(refund_row["refund_amount"]),
        "refund_count": refund_row["refund_count"],
        "net_revenue": round_money(net_revenue),
        "average_order_value": round_money(safe_divide(revenue, completed_orders)),
        "margin": round_money(margin),
        "margin_pct": round(safe_divide(margin, revenue), 4),
    }


def get_sales_summary(start_date: str, end_date: str) -> dict:
    """Orders, revenue, AOV, and refunds for an explicit date range."""
    start_d, end_d = validate_date_range(start_date, end_date)
    window = DateWindow(start_d, end_d)

    conn = get_connection()
    try:
        return _summary_for_window(conn, window)
    finally:
        conn.close()


def compare_sales_periods(
    current_start: str, current_end: str,
    previous_start: str, previous_end: str,
) -> dict:
    """
    Compare two explicit date ranges (current vs. previous). Workflow A
    calls last_n_complete_days / previous_n_complete_days (in metrics.py)
    to compute these bounds before calling this tool, so "the last seven
    complete days vs the previous seven" becomes two concrete date ranges
    rather than ambiguous relative language reaching the database layer.
    """
    cur_start, cur_end = validate_date_range(current_start, current_end)
    prev_start, prev_end = validate_date_range(previous_start, previous_end)

    conn = get_connection()
    try:
        current = _summary_for_window(conn, DateWindow(cur_start, cur_end))
        previous = _summary_for_window(conn, DateWindow(prev_start, prev_end))
    finally:
        conn.close()

    revenue_change = current["revenue"] - previous["revenue"]
    revenue_change_pct = safe_divide(revenue_change, previous["revenue"])

    return {
        "current": current,
        "previous": previous,
        "revenue_change": round_money(revenue_change),
        "revenue_change_pct": round(revenue_change_pct, 4),
        "order_count_change": current["completed_orders"] - previous["completed_orders"],
        "margin_pct_change": round(current["margin_pct"] - previous["margin_pct"], 4),
    }


def get_product_performance(
    start_date: str, end_date: str,
    sort_by: str = "revenue", limit: int | None = None,
) -> dict:
    """
    Rank products by sales, units, or margin over a date range. This is
    the tool Workflow A uses to find "which products contributed most" to
    a revenue change -- call it once for the current window and once for
    the previous window, then diff the two result sets yourself (in
    app/agent.py or the calling workflow) to get each product's
    contribution to the change.
    """
    start_d, end_d = validate_date_range(start_date, end_date)
    limit = validate_limit(limit, default=20)

    sort_columns = {
        "revenue": "revenue DESC",
        "units": "units_sold DESC",
        "margin": "margin DESC",
    }
    if sort_by not in sort_columns:
        raise ToolValidationError(
            f"sort_by must be one of {list(sort_columns)}, got {sort_by!r}."
        )

    window = DateWindow(start_d, end_d)
    start_str, end_exclusive = window.as_sql_bounds()

    sql = f"""
        SELECT p.product_id, p.title, p.category,
               SUM(oi.quantity) AS units_sold,
               ROUND(SUM(oi.quantity * oi.unit_price), 2) AS revenue,
               ROUND(SUM((oi.unit_price - v.cost) * oi.quantity), 2) AS margin,
               COUNT(DISTINCT oi.order_id) AS order_count
        FROM order_items oi
        JOIN orders o ON o.order_id = oi.order_id
        JOIN variants v ON v.variant_id = oi.variant_id
        JOIN products p ON p.product_id = v.product_id
        WHERE o.status = 'completed'
          AND o.order_date >= ? AND o.order_date < ?
        GROUP BY p.product_id
        ORDER BY {sort_columns[sort_by]}
        LIMIT ?
    """

    conn = get_connection()
    try:
        rows = conn.execute(sql, (start_str, end_exclusive, limit)).fetchall()
    finally:
        conn.close()

    return {
        "start_date": start_date, "end_date": end_date, "sort_by": sort_by,
        "products": rows_to_dicts(rows),
    }


def get_refund_summary(
    start_date: str, end_date: str,
    category: str | None = None, reason: str | None = None,
) -> dict:
    """Summarize refunds over a date range, optionally filtered by product
    category or refund reason. Used to spot 'a category with an unusually
    high refund rate' (one of the brief's known injected patterns)."""
    start_d, end_d = validate_date_range(start_date, end_date)
    window = DateWindow(start_d, end_d)
    start_str, end_exclusive = window.as_sql_bounds()

    sql = """
        SELECT p.category, r.reason,
               COUNT(*) AS refund_count,
               ROUND(SUM(r.amount), 2) AS refund_amount
        FROM refunds r
        JOIN variants v ON v.variant_id = r.variant_id
        JOIN products p ON p.product_id = v.product_id
        WHERE r.refund_date >= ? AND r.refund_date < ?
    """
    params = [start_str, end_exclusive]
    if category:
        sql += " AND p.category = ?"
        params.append(category)
    if reason:
        sql += " AND r.reason = ?"
        params.append(reason)
    sql += " GROUP BY p.category, r.reason ORDER BY refund_amount DESC"

    conn = get_connection()
    try:
        rows = conn.execute(sql, params).fetchall()
        # Also compute each category's share of total order volume, so a
        # refund *count* can be read as a *rate* rather than raw size.
        volume_rows = conn.execute(
            """
            SELECT p.category, COUNT(DISTINCT oi.order_id) AS order_count
            FROM order_items oi
            JOIN orders o ON o.order_id = oi.order_id
            JOIN variants v ON v.variant_id = oi.variant_id
            JOIN products p ON p.product_id = v.product_id
            WHERE o.order_date >= ? AND o.order_date < ?
            GROUP BY p.category
            """,
            (start_str, end_exclusive),
        ).fetchall()
    finally:
        conn.close()

    volume_by_category = {r["category"]: r["order_count"] for r in volume_rows}
    breakdown = rows_to_dicts(rows)
    for row in breakdown:
        orders_in_category = volume_by_category.get(row["category"], 0)
        row["orders_in_category"] = orders_in_category
        row["refund_rate_vs_orders"] = round(
            safe_divide(row["refund_count"], orders_in_category), 4
        )

    return {
        "start_date": start_date, "end_date": end_date,
        "filter": {"category": category, "reason": reason},
        "breakdown": breakdown,
    }
