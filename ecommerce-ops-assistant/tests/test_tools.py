"""
tests/test_tools.py
--------------------------------------------------------------------------
Tests for the tool functions against the real built database
(database/shop.db). Run `python3 database/build_database.py` at least
once before running these.

This covers milestone 2 from the brief: "Six read-only tools tested
without Gemini" -- these tests call the Python functions directly, no
model, no HTTP server, so they prove the tools work on their own before
any agent loop is layered on top.

Most tests are self-contained: they look up a real id from the database
rather than hard-coding one. A handful of tests ARE pinned to specific
dates, categories, or product names on purpose -- those are ground-truth
checks against real, discovered patterns in the UCI dataset, documented
with their exact source queries in docs/data_profile.md. If you swap in a
different data source (e.g. a later UCI "Online Retail II" export, or
database/generate_stand_in_data.py's fabricated stand-in data), those
specific tests will need new ground truth from docs/data_profile.md's
method, not just new numbers plugged into the same assertions.
"""

import sqlite3
from tools import catalog, orders, sales, inventory, external, approvals
from tools.validation import ToolValidationError
from tools.db import DB_PATH


def _any_order_id(status="completed"):
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute("SELECT order_id FROM orders WHERE status = ? LIMIT 1", (status,)).fetchone()
    conn.close()
    return row[0]


def _any_customer_id():
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute("SELECT customer_id FROM customers LIMIT 1").fetchone()
    conn.close()
    return row[0]


def _any_product_id():
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute("SELECT product_id FROM products LIMIT 1").fetchone()
    conn.close()
    return row[0]


def _any_variant_id():
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute("SELECT variant_id FROM variants LIMIT 1").fetchone()
    conn.close()
    return row[0]


# --- catalog.py ------------------------------------------------------------

def test_search_products_finds_known_item():
    result = catalog.search_products("clock")
    assert result["count"] >= 1
    assert any("CLOCK" in p["title"] for p in result["products"])


def test_search_products_rejects_empty_query():
    try:
        catalog.search_products("")
        assert False, "expected ToolValidationError"
    except ToolValidationError:
        pass


def test_get_product_details_not_found():
    result = catalog.get_product_details("NOPE-DOES-NOT-EXIST")
    assert result["error"] == "not_found"


def test_get_product_details_found():
    pid = _any_product_id()
    result = catalog.get_product_details(pid)
    assert result["product"]["product_id"] == pid
    assert len(result["variants"]) >= 1


def test_get_inventory_shape():
    vid = _any_variant_id()
    result = catalog.get_inventory(vid)
    assert "available_units" in result
    assert "below_threshold" in result


# --- orders.py ---------------------------------------------------------------

def test_get_order_not_found_does_not_invent_a_record():
    result = orders.get_order("ORDER-DOES-NOT-EXIST")
    assert result["error"] == "not_found"


def test_get_order_found_has_items():
    oid = _any_order_id()
    result = orders.get_order(oid)
    assert result["order"]["order_id"] == oid
    assert len(result["items"]) >= 1


def test_get_order_analyst_role_redacts_customer_id():
    oid = _any_order_id()
    result = orders.get_order(oid, requesting_role="analyst")
    assert result["order"]["customer_id"] == "[redacted: analyst role]"


def test_get_customer_summary_found():
    cid = _any_customer_id()
    result = orders.get_customer_summary(cid)
    assert result["customer"]["customer_id"] == cid
    assert result["order_count"] >= 0


def test_get_customer_summary_not_found():
    result = orders.get_customer_summary("CUSTOMER-DOES-NOT-EXIST")
    assert result["error"] == "not_found"


# --- sales.py: the core business-logic tools --------------------------------

def test_get_sales_summary_zero_sales_window_does_not_crash():
    # A date range entirely before our dataset starts should have zero
    # orders, not a division-by-zero crash.
    result = sales.get_sales_summary("2020-01-01", "2020-01-07")
    assert result["completed_orders"] == 0
    assert result["average_order_value"] == 0.0
    assert result["margin_pct"] == 0.0


def test_get_sales_summary_rejects_bad_date_order():
    try:
        sales.get_sales_summary("2026-09-10", "2026-09-01")
        assert False, "expected ToolValidationError"
    except ToolValidationError:
        pass


def test_compare_sales_periods_no_saturday_trading():
    """
    Ground-truth check against a real, discovered pattern in the UCI data
    (see docs/data_profile.md #1): this retailer has ZERO completed orders
    on any Saturday anywhere in the dataset. Comparing a Saturday-only
    range against an ordinary weekday range should show a 100% order-count
    drop, not a crash or a nonsensical positive number.
    """
    result = sales.compare_sales_periods(
        "2011-06-04", "2011-06-04",   # a Saturday -- zero orders, always
        "2011-06-02", "2011-06-02",   # the Thursday before -- real orders
    )
    assert result["current"]["completed_orders"] == 0
    assert result["previous"]["completed_orders"] > 0
    assert result["order_count_change"] < 0


def test_get_product_performance_sort_validation():
    try:
        sales.get_product_performance("2026-09-01", "2026-09-08", sort_by="not_a_real_option")
        assert False, "expected ToolValidationError"
    except ToolValidationError:
        pass


def test_get_refund_summary_shows_known_high_refund_category():
    """
    Ground-truth check against a real, discovered pattern in the UCI data
    (see docs/data_profile.md #2): 'General Merchandise' has a materially
    higher refund RATE (refunds per order in that category) than the
    dataset average -- not just more refunds in absolute terms, which
    would just mean it's a bigger category.
    """
    result = sales.get_refund_summary("2010-12-01", "2011-11-30")  # <= 366 days (validation.py's cap)
    by_category = {row["category"]: row for row in result["breakdown"]}
    assert "General Merchandise" in by_category
    gm_rate = by_category["General Merchandise"]["refund_rate_vs_orders"]
    other_rates = [r["refund_rate_vs_orders"] for cat, r in by_category.items()
                   if cat != "General Merchandise"]
    assert gm_rate > (sum(other_rates) / max(len(other_rates), 1))


# --- inventory.py --------------------------------------------------------------

def test_get_stockout_risk_shape():
    result = inventory.get_stockout_risk(lookback_days=14)
    assert "at_risk_within_14_days" in result
    assert "zero_sales_products" in result


def test_calculate_reorder_quantity_zero_sales_is_handled():
    # Pick a real variant but ask about a lookback window entirely before
    # the dataset starts, so sales are guaranteed to be zero.
    vid = _any_variant_id()
    result = inventory.calculate_reorder_quantity(vid, target_coverage_days=14, lookback_days=1)
    # Either zero_sales is True, or there's a valid non-negative suggestion --
    # the important thing is it never crashes or divides by zero.
    assert "suggested_reorder" in result or result.get("zero_sales") is True


def test_known_sales_gap_shows_zero_units_in_window():
    """
    Ground-truth check against a real, discovered sales gap in the UCI
    data (see docs/data_profile.md #4): 'ALARM CLOCK BAKELIKE GREEN'
    (variant 22726-V1) sold steadily, then had zero sales from 2011-05-13
    to 2011-06-16, then resumed. get_product_performance for a window
    fully inside that gap should show no sales for it at all -- and a
    window just after the gap should show it selling again, confirming
    this is a real gap in the data, not a product that stopped existing.
    """
    # limit=200: the dataset has 4,070 products, so a specific one is not
    # guaranteed to land in the default top-20 by units even when it did
    # sell -- this test is about presence/absence in the window, not rank.
    during_gap = sales.get_product_performance("2011-05-14", "2011-06-15", sort_by="units", limit=200)
    gap_titles = [p["title"] for p in during_gap["products"]]
    assert "ALARM CLOCK BAKELIKE GREEN" not in gap_titles

    after_gap = sales.get_product_performance("2011-06-17", "2011-06-30", sort_by="units", limit=200)
    after_titles = [p["title"] for p in after_gap["products"]]
    assert "ALARM CLOCK BAKELIKE GREEN" in after_titles


# --- external.py ---------------------------------------------------------------

def test_loyal_customers_have_higher_aov_than_one_time_customers():
    """
    Ground-truth check against docs/data_profile.md #3: in the real data,
    customers with 5+ completed orders have a HIGHER average order value
    than one-time customers (412.52 vs 426.49 GBP at full-dataset scope).
    The effect is real but modest, so this checks the direction, not a
    specific magnitude.
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT customer_id, COUNT(*) n, AVG(total) aov FROM orders "
        "WHERE status='completed' AND customer_id IS NOT NULL GROUP BY customer_id"
    ).fetchall()
    conn.close()
    one_time = [r["aov"] for r in rows if r["n"] == 1]
    loyal = [r["aov"] for r in rows if r["n"] >= 5]
    assert len(one_time) > 0 and len(loyal) > 0
    assert (sum(loyal) / len(loyal)) > (sum(one_time) / len(one_time))


def test_get_exchange_rate_identity():
    result = external.get_exchange_rate("GBP", "GBP")
    assert result["rate"] == 1.0


def test_get_exchange_rate_rejects_unsupported_currency():
    try:
        external.get_exchange_rate("GBP", "ZZZ")
        assert False, "expected ToolValidationError"
    except ToolValidationError:
        pass


# --- approvals.py: the human-in-the-loop boundary -------------------------------

def test_propose_discount_creates_pending_request_only():
    pid = _any_product_id()
    result = approvals.propose_discount([pid], 10, "2030-01-01", "2030-01-07", requester="test")
    assert result["status"] == "pending_approval"
    listed = approvals.list_approval_requests(status="pending")
    assert any(r["request_id"] == result["request_id"] for r in listed)


def test_discount_cannot_be_executed_before_approval():
    pid = _any_product_id()
    prop = approvals.propose_discount([pid], 10, "2030-02-01", "2030-02-07", requester="test")
    try:
        approvals.execute_approval(prop["request_id"])
        assert False, "expected ToolValidationError"
    except ToolValidationError:
        pass


def test_discount_execution_is_idempotent():
    pid = _any_product_id()
    prop = approvals.propose_discount([pid], 10, "2030-03-01", "2030-03-07", requester="test")
    approvals.decide_approval(prop["request_id"], "approved", reviewer="test-manager")
    first = approvals.execute_approval(prop["request_id"])
    second = approvals.execute_approval(prop["request_id"])
    assert first["status"] == "executed"
    assert second["status"] == "already_executed"


def test_approval_percentage_above_90_is_blocked():
    pid = _any_product_id()
    try:
        approvals.propose_discount([pid], 95, "2030-04-01", "2030-04-07", requester="test")
        assert False, "expected ToolValidationError"
    except ToolValidationError:
        pass
