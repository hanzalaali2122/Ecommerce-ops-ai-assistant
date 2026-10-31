# `app/main.py` — explained

**What it is:** the FastAPI application — the thin HTTP layer that ties
everything else together. It deliberately contains almost no business
logic of its own; every endpoint validates the request shape, checks the
caller's role, and calls into `app/agent.py` / `app/mock_agent.py` /
`tools/*.py`. Keeping logic out of this file is exactly what lets
`tools/*.py` be unit-tested completely independently of any running web
server (see `tests/test_tools.py`, which never imports or starts
`app/main.py` at all).

## The endpoints, grouped by the brief's "Application areas" table

**Chat assistant**
- `POST /chat` — the main entry point. Picks `app/agent.py` (real Gemini)
  or `app/mock_agent.py` (rule-based fallback) based solely on whether
  `GEMINI_API_KEY` is set in the environment — the response shape is
  identical either way, so this choice is invisible to whoever's calling
  the API.

**Investigation view**
- `GET /investigations/{request_id}` — every tool call made while
  answering one `/chat` request, in order, with timing and status. Reads
  straight from the `tool_runs` table (written by `tools/audit.py`
  during the `/chat` call). Returns 404 if nothing was logged under that
  ID, rather than an empty-but-"successful" response.

**Approval inbox**
- `GET /approvals` — list proposals, optionally filtered by status.
- `POST /approvals/{id}/approve` / `/reject` — gated by
  `_require_manager()`: only the `manager` role can decide a proposal.
  This is the brief's "the model cannot approve its own request" rule
  made concrete at the HTTP layer too — even a human calling this API as
  `support` or `analyst` is refused with a 403.
- `POST /approvals/{id}/execute` — also manager-only; calls
  `tools/approvals.execute_approval`, which is itself idempotent (safe to
  call twice — see that file's explained doc).

**Direct tool access**
- `POST /tools/propose_discount` / `/tools/propose_inventory_alert` —
  lets the frontend (or a test) trigger Workflow D's proposal step
  without going through the chat loop at all. Useful because
  `app/mock_agent.py` can't safely parse a free-text discount request
  (see that file's explained doc) — this is the honest alternative route
  it points people to.

**Operational**
- `GET /health` — reports which agent mode is active (`gemini` vs
  `mock`) and whether the database file exists. Cheap to check before
  debugging anything else.

## CORS

`allow_origins=["*"]` — permissive, by design, for local development
only (the frontend runs on a different port than the API). The comment
in the file says plainly: tighten this before any real deployment.

## Serving the frontend

The last few lines mount `frontend/` as static files at `/`, if that
directory exists — so the entire project (API + simple frontend) can run
from one command: `uvicorn app.main:app --reload --port 8000`.

## How this connects to the rest of the project

Imports `app/auth.py` (role/user resolution), `app/models.py` (request/
response shapes), `tools/db.py` (direct read for the investigation
endpoint), `tools/validation.py` (to catch `ToolValidationError` and turn
it into a proper HTTP 400), and `tools/approvals.py` (the approval-decision
functions a human action triggers through this file, and only this
file).
