"""
tools/orders.py
--------------------------------------------------------------------------
Tools for looking up a single order (Workflow C) and a single customer's
purchase history.

Access control note (brief: "enforce the signed-in user's access"): the
`requesting_role` parameter is threaded through from app/auth.py. In this
project's simplified role model, 'support' and 'manager' can see full
order/customer detail; 'analyst' can see aggregate sales data (sales.py)
but not individual customer PII such as email -- see the redaction below.
This is enforced here, in the tool itself, not just hoped for in the
prompt, because the brief is explicit that sensitive actions and data
access must be checked in code, not left to the model's judgment.
"""

from tools.db import get_connection, rows_to_dicts
from tools.validation import require_non_empty_string


def get_order(order_id: str, requesting_role: str = "support") -> dict:
    """Retrieve one order: its status, line items, and any refunds against it."""
    order_id = require_non_empty_string(order_id, "order_id")

    conn = get_connection()
    try:
        order = conn.execute(
            "SELECT order_id, customer_id, order_date, status, currency, "
            "subtotal, discount_total, total FROM orders WHERE order_id = ?",
            (order_id,),
        ).fetchone()
        if order is None:
            return {"error": "not_found", "message": f"No order with id {order_id!r}."}

        items = conn.execute(
            """
            SELECT oi.variant_id, p.title AS product_title, oi.quantity,
                   oi.unit_price, oi.discount,
                   ROUND(oi.quantity * oi.unit_price, 2) AS line_total
            FROM order_items oi
            JOIN variants v ON v.variant_id = oi.variant_id
            JOIN products p ON p.product_id = v.product_id
            WHERE oi.order_id = ?
            """,
            (order_id,),
        ).fetchall()

        refunds = conn.execute(
            "SELECT refund_id, variant_id, refund_date, amount, reason "
            "FROM refunds WHERE order_id = ?",
            (order_id,),
        ).fetchall()
    finally:
        conn.close()

    result = {
        "order": dict(order),
        "items": rows_to_dicts(items),
        "refunds": rows_to_dicts(refunds),
    }
    if requesting_role == "analyst":
        # Analysts can see the order exists and its numbers, but not which
        # customer placed it -- a light example of role-based redaction.
        result["order"]["customer_id"] = "[redacted: analyst role]"
    return result


def get_customer_summary(customer_id: str, requesting_role: str = "support") -> dict:
    """Summarize one customer's purchase history: order count, total spend,
    average order value, and their most recent orders."""
    customer_id = require_non_empty_string(customer_id, "customer_id")

    conn = get_connection()
    try:
        customer = conn.execute(
            "SELECT customer_id, name, email, country, created_date FROM customers WHERE customer_id = ?",
            (customer_id,),
        ).fetchone()
        if customer is None:
            return {"error": "not_found", "message": f"No customer with id {customer_id!r}."}

        agg = conn.execute(
            """
            SELECT COUNT(*) AS order_count,
                   COALESCE(SUM(total), 0) AS lifetime_revenue,
                   COALESCE(AVG(total), 0) AS avg_order_value
            FROM orders WHERE customer_id = ? AND status = 'completed'
            """,
            (customer_id,),
        ).fetchone()

        recent_orders = conn.execute(
            "SELECT order_id, order_date, status, total FROM orders "
            "WHERE customer_id = ? ORDER BY order_date DESC LIMIT 10",
            (customer_id,),
        ).fetchall()
    finally:
        conn.close()

    customer_dict = dict(customer)
    if requesting_role == "analyst":
        customer_dict["email"] = "[redacted: analyst role]"

    return {
        "customer": customer_dict,
        "order_count": agg["order_count"],
        "lifetime_revenue": round(agg["lifetime_revenue"], 2),
        "avg_order_value": round(agg["avg_order_value"], 2),
        "recent_orders": rows_to_dicts(recent_orders),
    }
