"""
tools/approvals.py
--------------------------------------------------------------------------
This is the only file in the project that writes anything the model's own
tool calls can trigger -- and even then, it never executes a real action.
It only ever INSERTs a row into approval_requests with status='pending'.

The brief is explicit about this boundary: "A separate application
endpoint executes the approved payload. The model cannot approve its own
request or change the action after approval." So the flow is:

    1. Model calls propose_discount(...) or propose_inventory_alert(...)
       -> a pending approval_requests row is created. This is as far as
       the model's own tool-calling loop can ever go.
    2. A human looks at the exact payload (not a paraphrase of it) in the
       Approval inbox and calls the app's /approvals/{id}/approve or
       /reject endpoint (app/main.py) -- outside the model's control.
    3. Only an 'approved' request can then be executed, and only once
       (app/main.py checks executed_at before running it, so a duplicate
       execute request is a no-op the second time -- the brief's
       "Duplicate execution request -> execute no more than once" case).

propose_* functions here never touch orders/products/discount_codes --
they only ever write to approval_requests. The actual execute_* functions
at the bottom of this file DO touch real tables, but app/main.py is the
only caller allowed to invoke them, and only for a request whose status is
already 'approved'.
"""

import json
import uuid
from datetime import datetime, timezone

from metrics import round_money, safe_divide
from tools.db import get_connection, rows_to_dicts
from tools.validation import (
    require_non_empty_string, validate_date_range, validate_percentage,
    ToolValidationError,
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def propose_discount(
    product_ids: list[str], percentage: float,
    start_date: str, end_date: str, requester: str,
) -> dict:
    """
    Prepare a discount proposal for human approval. Also computes the
    estimated margin impact up front (using each product's recent sales
    velocity and cost) so the approver sees the consequence, not just the
    request -- this directly supports Workflow D's "check margin after
    discount" step.
    """
    if not product_ids or not isinstance(product_ids, list):
        raise ToolValidationError("product_ids must be a non-empty list of product ids.")
    pct = validate_percentage(percentage)
    validate_date_range(start_date, end_date)
    requester = require_non_empty_string(requester, "requester")

    conn = get_connection()
    try:
        impact_rows = []
        for pid in product_ids:
            row = conn.execute(
                """
                SELECT p.product_id, p.title,
                       COALESCE(SUM(oi.quantity), 0) AS recent_units_sold,
                       AVG(v.price) AS avg_price, AVG(v.cost) AS avg_cost
                FROM products p
                JOIN variants v ON v.product_id = p.product_id
                LEFT JOIN order_items oi ON oi.variant_id = v.variant_id
                LEFT JOIN orders o ON o.order_id = oi.order_id
                    AND o.status = 'completed'
                    AND o.order_date >= date('now', '-30 day')
                WHERE p.product_id = ?
                GROUP BY p.product_id
                """,
                (pid,),
            ).fetchone()
            if row is None:
                raise ToolValidationError(f"product_id {pid!r} does not exist.")

            discounted_price = round_money(row["avg_price"] * (1 - pct / 100))
            margin_before = row["avg_price"] - row["avg_cost"]
            margin_after = discounted_price - row["avg_cost"]
            impact_rows.append({
                "product_id": row["product_id"],
                "title": row["title"],
                "recent_units_sold_30d": row["recent_units_sold"],
                "current_avg_price": round_money(row["avg_price"]),
                "discounted_price": discounted_price,
                "margin_pct_before": round(safe_divide(margin_before, row["avg_price"]), 4),
                "margin_pct_after": round(safe_divide(margin_after, discounted_price), 4),
            })
    finally:
        conn.close()

    request_id = str(uuid.uuid4())
    payload = {
        "product_ids": product_ids,
        "percentage": pct,
        "start_date": start_date,
        "end_date": end_date,
        "estimated_impact": impact_rows,
    }

    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO approval_requests "
            "(request_id, action, payload, status, requester, created_at) "
            "VALUES (?, 'discount', ?, 'pending', ?, ?)",
            (request_id, json.dumps(payload), requester, _now_iso()),
        )
        conn.commit()
    finally:
        conn.close()

    return {
        "request_id": request_id,
        "status": "pending_approval",
        "action": "discount",
        "payload": payload,
        "message": "Discount proposal created. It will not take effect until a "
                    "manager reviews and approves it in the Approval inbox.",
    }


def propose_inventory_alert(variant_id: str, threshold: int, requester: str) -> dict:
    """Prepare a proposed change to a variant's reorder threshold for approval."""
    variant_id = require_non_empty_string(variant_id, "variant_id")
    requester = require_non_empty_string(requester, "requester")
    try:
        threshold = int(threshold)
    except (TypeError, ValueError):
        raise ToolValidationError("threshold must be a whole number.")
    if threshold < 0:
        raise ToolValidationError("threshold cannot be negative.")

    conn = get_connection()
    try:
        current = conn.execute(
            "SELECT available_units, reorder_threshold FROM inventory WHERE variant_id = ?",
            (variant_id,),
        ).fetchone()
        if current is None:
            raise ToolValidationError(f"No inventory record for variant {variant_id!r}.")
    finally:
        conn.close()

    request_id = str(uuid.uuid4())
    payload = {
        "variant_id": variant_id,
        "current_threshold": current["reorder_threshold"],
        "proposed_threshold": threshold,
        "current_available_units": current["available_units"],
    }

    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO approval_requests "
            "(request_id, action, payload, status, requester, created_at) "
            "VALUES (?, 'inventory_alert', ?, 'pending', ?, ?)",
            (request_id, json.dumps(payload), requester, _now_iso()),
        )
        conn.commit()
    finally:
        conn.close()

    return {
        "request_id": request_id,
        "status": "pending_approval",
        "action": "inventory_alert",
        "payload": payload,
        "message": "Inventory alert threshold change proposed. It will not take "
                    "effect until approved in the Approval inbox.",
    }


# ---------------------------------------------------------------------------
# Everything below this line is deliberately NOT part of the model's tool
# catalog (app/schemas.py does not expose these as callable functions).
# app/main.py's approval endpoints call these directly, after independently
# checking the approval_requests row's status.
# ---------------------------------------------------------------------------

def list_approval_requests(status: str | None = None) -> list[dict]:
    conn = get_connection()
    try:
        if status:
            rows = conn.execute(
                "SELECT * FROM approval_requests WHERE status = ? ORDER BY created_at DESC",
                (status,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM approval_requests ORDER BY created_at DESC"
            ).fetchall()
    finally:
        conn.close()
    results = rows_to_dicts(rows)
    for r in results:
        r["payload"] = json.loads(r["payload"])
    return results


def decide_approval(request_id: str, decision: str, reviewer: str) -> dict:
    """decision is 'approved' or 'rejected'. Called only by a human action
    in app/main.py -- never by the model's own tool loop."""
    if decision not in ("approved", "rejected"):
        raise ToolValidationError("decision must be 'approved' or 'rejected'.")

    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM approval_requests WHERE request_id = ?", (request_id,)
        ).fetchone()
        if row is None:
            raise ToolValidationError(f"No approval request with id {request_id!r}.")
        if row["status"] != "pending":
            raise ToolValidationError(
                f"Request {request_id} is already {row['status']!r}; it cannot be "
                f"decided again."
            )
        conn.execute(
            "UPDATE approval_requests SET status = ?, reviewer = ?, decided_at = ? "
            "WHERE request_id = ?",
            (decision, reviewer, _now_iso(), request_id),
        )
        conn.commit()
    finally:
        conn.close()

    return {"request_id": request_id, "status": decision, "reviewer": reviewer}


def execute_approval(request_id: str) -> dict:
    """
    Execute an already-approved request's exact payload. Idempotent: if
    executed_at is already set, this is a no-op that reports the earlier
    execution instead of applying the change twice -- this is what
    satisfies the brief's "prevent duplicate writes with idempotency" and
    "Execute an approved write no more than once" requirements.
    """
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM approval_requests WHERE request_id = ?", (request_id,)
        ).fetchone()
        if row is None:
            raise ToolValidationError(f"No approval request with id {request_id!r}.")
        if row["status"] == "executed" or row["executed_at"]:
            # Idempotency: executing an already-executed request is a safe
            # no-op that reports the prior execution, rather than an error
            # and rather than applying the change a second time.
            return {
                "request_id": request_id, "status": "already_executed",
                "executed_at": row["executed_at"],
                "message": "This request was already executed; it was not applied again.",
            }
        if row["status"] != "approved":
            raise ToolValidationError(
                f"Request {request_id} has status {row['status']!r}; only an "
                f"'approved' request can be executed."
            )

        payload = json.loads(row["payload"])
        if row["action"] == "discount":
            code = f"AUTO-{request_id[:8].upper()}"
            conn.execute(
                "INSERT INTO discount_codes (code, percentage, start_date, expiry_date) "
                "VALUES (?, ?, ?, ?)",
                (code, payload["percentage"], payload["start_date"], payload["end_date"]),
            )
            result_detail = {"discount_code_created": code}
        elif row["action"] == "inventory_alert":
            conn.execute(
                "UPDATE inventory SET reorder_threshold = ? WHERE variant_id = ?",
                (payload["proposed_threshold"], payload["variant_id"]),
            )
            result_detail = {"variant_id": payload["variant_id"],
                              "new_threshold": payload["proposed_threshold"]}
        else:
            raise ToolValidationError(f"Unknown action type {row['action']!r}.")

        conn.execute(
            "UPDATE approval_requests SET status = 'executed', executed_at = ? WHERE request_id = ?",
            (_now_iso(), request_id),
        )
        conn.commit()
    finally:
        conn.close()

    return {"request_id": request_id, "status": "executed", **result_detail}
