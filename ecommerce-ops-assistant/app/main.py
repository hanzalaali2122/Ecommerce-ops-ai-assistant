"""
app/main.py
--------------------------------------------------------------------------
The FastAPI application. This is the thin HTTP layer the frontend (and
anyone else) talks to. It does NOT contain business logic itself -- every
endpoint here just validates the request shape (via app/models.py),
checks the caller's role (via app/auth.py), and calls into app/agent.py,
tools/*.py, or database/shop.db. Keeping logic out of this file is what
lets tools/*.py be unit-tested completely independently of any web
server (see tests/test_tools.py).

ENDPOINTS, grouped by the brief's "Application areas" table:

  Chat assistant
    POST /chat                 -- ask a business question in plain English

  Investigation view
    GET  /investigations/{request_id}   -- every tool call made answering
                                            one /chat request, with timing
                                            and status (the audit trail)

  Approval inbox
    GET  /approvals                     -- list proposals (optionally by status)
    POST /approvals/{id}/approve        -- human approves a proposal
    POST /approvals/{id}/reject         -- human rejects a proposal
    POST /approvals/{id}/execute        -- execute an approved proposal
                                            (idempotent -- safe to call twice)

  Direct tool access (useful for the frontend / testing without going
  through the chat loop, and for the workflow-D caveat in mock mode)
    POST /tools/propose_discount
    POST /tools/propose_inventory_alert

Run this with:
    uvicorn app.main:app --reload --port 8000
from the project's root directory (so the `tools`, `app`, and `metrics`
imports resolve).
"""

import os
import sqlite3

from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.auth import get_current_role, get_current_user
from app.models import ChatRequest, ChatResponse, ApprovalDecisionRequest
from tools.db import get_connection
from tools.validation import ToolValidationError
from tools import approvals as approvals_tools

app = FastAPI(
    title="Ecommerce Operations Assistant",
    description="A store operations assistant that investigates sales, inventory, "
                "customers, and orders, and prepares sensitive actions for human approval.",
    version="0.1.0",
)

# Permissive CORS for local development -- the frontend is served from a
# different port (a plain `python -m http.server` or similar). Tighten
# this before any real deployment.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Chat assistant
# ---------------------------------------------------------------------------
@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest, role: str = Depends(get_current_role), user: str = Depends(get_current_user)):
    """
    Runs one investigation. Uses the real Gemini tool-calling loop
    (app/agent.py) if GEMINI_API_KEY is set, otherwise falls back to the
    rule-based app/mock_agent.py so the whole system stays testable
    without any API key. Either way, the response shape is identical.
    """
    if os.environ.get("GEMINI_API_KEY"):
        from app.agent import run_investigation
        try:
            result = run_investigation(req.question, role=role, requester=user)
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Model call failed: {exc}")
    else:
        from app.mock_agent import run_investigation_mock
        result = run_investigation_mock(req.question, role=role, requester=user)

    return result


# ---------------------------------------------------------------------------
# Investigation view (audit trail for one /chat call)
# ---------------------------------------------------------------------------
@app.get("/investigations/{request_id}")
def get_investigation(request_id: str):
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT run_id, request_id, tool_name, arguments, result_summary, "
            "status, duration_ms, started_at FROM tool_runs WHERE request_id = ? "
            "ORDER BY started_at ASC",
            (request_id,),
        ).fetchall()
    finally:
        conn.close()
    if not rows:
        raise HTTPException(status_code=404, detail="No tool runs found for this request_id.")
    return {"request_id": request_id, "tool_runs": [dict(r) for r in rows]}


# ---------------------------------------------------------------------------
# Approval inbox
# ---------------------------------------------------------------------------
@app.get("/approvals")
def list_approvals(status: str | None = None):
    return approvals_tools.list_approval_requests(status=status)


@app.post("/approvals/{request_id}/approve")
def approve(request_id: str, user: str = Depends(get_current_user), role: str = Depends(get_current_role)):
    _require_manager(role)
    try:
        return approvals_tools.decide_approval(request_id, "approved", reviewer=user)
    except ToolValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/approvals/{request_id}/reject")
def reject(request_id: str, user: str = Depends(get_current_user), role: str = Depends(get_current_role)):
    _require_manager(role)
    try:
        return approvals_tools.decide_approval(request_id, "rejected", reviewer=user)
    except ToolValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/approvals/{request_id}/execute")
def execute(request_id: str, role: str = Depends(get_current_role)):
    _require_manager(role)
    try:
        return approvals_tools.execute_approval(request_id)
    except ToolValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


def _require_manager(role: str):
    # Only a manager may decide or execute approvals -- this is the
    # brief's "The model cannot approve its own request" boundary made
    # concrete: even a human using 'support' or 'analyst' role cannot
    # approve a sensitive action through this API.
    if role != "manager":
        raise HTTPException(
            status_code=403,
            detail=f"Role {role!r} cannot approve, reject, or execute requests; requires 'manager'.",
        )


# ---------------------------------------------------------------------------
# Direct tool access for propose_* (handy for the frontend's "Propose"
# forms, and for testing Workflow D without going through chat/mock mode)
# ---------------------------------------------------------------------------
@app.post("/tools/propose_discount")
def propose_discount_endpoint(
    product_ids: list[str], percentage: float, start_date: str, end_date: str,
    user: str = Depends(get_current_user), role: str = Depends(get_current_role),
):
    if role not in ("manager", "support"):
        raise HTTPException(status_code=403, detail=f"Role {role!r} cannot propose a discount.")
    try:
        return approvals_tools.propose_discount(product_ids, percentage, start_date, end_date, requester=user)
    except ToolValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/tools/propose_inventory_alert")
def propose_inventory_alert_endpoint(
    variant_id: str, threshold: int,
    user: str = Depends(get_current_user), role: str = Depends(get_current_role),
):
    if role not in ("manager", "support"):
        raise HTTPException(status_code=403, detail=f"Role {role!r} cannot propose an inventory alert.")
    try:
        return approvals_tools.propose_inventory_alert(variant_id, threshold, requester=user)
    except ToolValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/health")
def health():
    mode = "gemini" if os.environ.get("GEMINI_API_KEY") else "mock"
    db_exists = os.path.exists(os.path.join(os.path.dirname(__file__), "..", "database", "shop.db"))
    return {"status": "ok", "agent_mode": mode, "database_ready": db_exists}


# Serve the simple frontend at / (so the whole project runs from one
# `uvicorn app.main:app` command during local development).
frontend_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "frontend")
if os.path.isdir(frontend_dir):
    app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")
