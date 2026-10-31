# `app/models.py` — explained

**What it is:** the Pydantic models defining the shape of every HTTP
request and response body the API uses. FastAPI uses these automatically
for two things: validating incoming JSON before any of the project's own
code runs, and generating the interactive API docs at `/docs`.

## The models

- **`ChatRequest`** — just `{"question": "..."}`, with `min_length=1` so
  an empty question is rejected at the door with a clear 422 error.
- **`EvidenceEntry`** — one entry in a response's `evidence` list: which
  tool ran, with what arguments, whether it succeeded, how long it took,
  and its `result_id` (the `tool_runs` row to look up for the full
  detail — see `tools/audit.py`).
- **`ChatResponse`** — the brief's "structured API response" shape, made
  concrete: `answer`, `data`, `evidence[]`, `proposed_actions`,
  `warnings`, `request_id`. Every field has a sensible empty default
  (`Field(default_factory=dict)` / `list`) so a minimal response is still
  a valid one.
- **`ApprovalDecisionRequest`** — `{"decision": "approved" | "rejected"}`,
  with a regex pattern constraint so anything else is rejected before it
  reaches `tools/approvals.py`'s own validation.
- **`ToolRunOut`** — the shape of one row from the `tool_runs` table, used
  by the `/investigations/{request_id}` endpoint.

## Why these models mirror the brief almost field-for-field

The brief's "Structured API responses" section lists exactly this set of
fields (`answer; data.current_revenue; ...; evidence[].tool;
evidence[].result_id; proposed_actions; warnings; request_id`). Matching
it directly here means the API's actual contract — enforced by Pydantic,
not just described in a doc — is traceable straight back to that
requirement.

## How this connects to the rest of the project

`app/main.py` uses `ChatResponse` as the `/chat` endpoint's
`response_model`, which means FastAPI will reject (with a clear error,
visible in development) any response that doesn't match this shape —
catching a shape mismatch between `app/agent.py` and the brief's own
spec automatically, rather than only when a frontend developer notices a
missing field by hand.
