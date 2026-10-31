"""
tools/inventory.py
--------------------------------------------------------------------------
Workflow B: "Which products may run out within two weeks, and how much
should we reorder?"

The formulas here are copied verbatim from the project brief so there is
no ambiguity about what "estimated days remaining" or "suggested reorder"
means:

    Average daily units  = units sold / days observed
    Estimated days remaining = available stock / average daily units
    Suggested reorder = max(0, target coverage days * average daily units
                             - available stock)

Both formulas divide by average daily units, which is zero for a product
with no recent sales -- metrics.safe_divide handles that (brief: "Zero
sales -> avoid division by zero"), and get_stockout_risk reports those
products separately with "zero_sales": true, exactly as the brief asks
("Handle zero-sales products separately").
"""

from metrics import DateWindow, last_n_complete_days, safe_divide
from tools.db import get_connection, rows_to_dicts
from tools.validation import require_non_empty_string, validate_positive_int, ToolValidationError


def get_stockout_risk(lookback_days: int | None = None, limit: int | None = None) -> dict:
    """
    Estimate, for every variant, how many days of stock remain given
    recent sales velocity, using a defined lookback window (default 14
    days, matching the "within two weeks" framing of Workflow B).
    """
    lookback = validate_positive_int(lookback_days or 14, "lookback_days", max_value=180)
    limit = validate_positive_int(limit or 50, "limit", max_value=200)

    window = last_n_complete_days(lookback)
    start_str, end_exclusive = window.as_sql_bounds()

    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT v.variant_id, v.product_id, p.title, i.available_units,
                   i.reorder_threshold,
                   COALESCE(SUM(oi.quantity), 0) AS units_sold_in_window
            FROM variants v
            JOIN products p ON p.product_id = v.product_id
            JOIN inventory i ON i.variant_id = v.variant_id
            LEFT JOIN order_items oi ON oi.variant_id = v.variant_id
            LEFT JOIN orders o ON o.order_id = oi.order_id
                AND o.status = 'completed'
                AND o.order_date >= ? AND o.order_date < ?
            GROUP BY v.variant_id
            """,
            (start_str, end_exclusive),
        ).fetchall()
    finally:
        conn.close()

    results = []
    for r in rows:
        avg_daily_units = safe_divide(r["units_sold_in_window"], lookback)
        zero_sales = avg_daily_units == 0
        days_remaining = None if zero_sales else round(
            safe_divide(r["available_units"], avg_daily_units), 1
        )
        results.append({
            "variant_id": r["variant_id"],
            "product_id": r["product_id"],
            "title": r["title"],
            "available_units": r["available_units"],
            "reorder_threshold": r["reorder_threshold"],
            "units_sold_in_window": r["units_sold_in_window"],
            "avg_daily_units": round(avg_daily_units, 2),
            "zero_sales": zero_sales,
            "estimated_days_remaining": days_remaining,
        })

    # Sort: soonest stockout first. Zero-sales products (no clear runway)
    # are pushed to the end rather than sorted as "infinite days remaining".
    results.sort(key=lambda r: (r["zero_sales"], r["estimated_days_remaining"] or 0))

    at_risk = [r for r in results if not r["zero_sales"] and r["estimated_days_remaining"] <= 14]

    return {
        "lookback_days": lookback,
        "window": {"start_date": window.start_date.isoformat(), "end_date": window.end_date.isoformat()},
        "at_risk_within_14_days": at_risk[:limit],
        "zero_sales_products": [r for r in results if r["zero_sales"]][:limit],
        "note": "available_units is synthesized stock data (see database/build_database.py); "
                "treat this as a modeled estimate, not live warehouse counts.",
    }


def calculate_reorder_quantity(
    variant_id: str, target_coverage_days: int | None = None, lookback_days: int | None = None
) -> dict:
    """
    Suggested reorder quantity for one variant, using the brief's formula.
    This depends on sales velocity (from order_items) and current stock
    (from inventory), so in the Gemini tool loop this call should happen
    *after* get_stockout_risk or get_inventory for the same variant, not
    in parallel with them (see the brief's note on dependent calls).
    """
    variant_id = require_non_empty_string(variant_id, "variant_id")
    target_coverage = validate_positive_int(target_coverage_days or 14, "target_coverage_days", max_value=180)
    lookback = validate_positive_int(lookback_days or 30, "lookback_days", max_value=180)

    window = last_n_complete_days(lookback)
    start_str, end_exclusive = window.as_sql_bounds()

    conn = get_connection()
    try:
        inv = conn.execute(
            "SELECT available_units FROM inventory WHERE variant_id = ?", (variant_id,)
        ).fetchone()
        if inv is None:
            return {"error": "not_found", "message": f"No inventory record for variant {variant_id!r}."}

        sold = conn.execute(
            """
            SELECT COALESCE(SUM(oi.quantity), 0) AS units_sold
            FROM order_items oi
            JOIN orders o ON o.order_id = oi.order_id
            WHERE oi.variant_id = ? AND o.status = 'completed'
              AND o.order_date >= ? AND o.order_date < ?
            """,
            (variant_id, start_str, end_exclusive),
        ).fetchone()
    finally:
        conn.close()

    avg_daily_units = safe_divide(sold["units_sold"], lookback)
    zero_sales = avg_daily_units == 0

    if zero_sales:
        return {
            "variant_id": variant_id,
            "zero_sales": True,
            "available_units": inv["available_units"],
            "suggested_reorder": 0,
            "note": "No sales in the lookback window, so a sales-velocity-based "
                    "reorder quantity cannot be calculated. Review manually before "
                    "reordering a zero-sales item.",
        }

    suggested = max(0, round(target_coverage * avg_daily_units - inv["available_units"]))

    return {
        "variant_id": variant_id,
        "zero_sales": False,
        "lookback_days": lookback,
        "target_coverage_days": target_coverage,
        "avg_daily_units": round(avg_daily_units, 2),
        "available_units": inv["available_units"],
        "suggested_reorder": suggested,
        "caveat": "This is a starting estimate based on recent sales velocity only. "
                  "It does not account for seasonality, supplier lead times, or demand "
                  "that earlier stockouts may have suppressed.",
    }
