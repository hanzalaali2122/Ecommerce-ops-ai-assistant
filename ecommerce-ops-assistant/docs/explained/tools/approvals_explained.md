# `tools/approvals.py` — explained

**What it is:** the human-in-the-loop boundary. The brief is explicit:
*"the model cannot approve its own request or change the action after
approval."* This file is where that rule becomes real code, not just a
system-prompt instruction the model could ignore.

## The three-step flow this file implements

```
1. Model calls propose_discount(...) or propose_inventory_alert(...)
      -> writes ONE row to approval_requests, status='pending'.
      -> This is as far as the model's own tool-calling loop can EVER go.

2. A human looks at the exact payload (not a summary of it) in the
   Approval inbox, and calls POST /approvals/{id}/approve or /reject
   (app/main.py) -- a step the model has no access to.

3. Only an 'approved' request can be executed, and only once.
```

## `propose_discount(product_ids, percentage, start_date, end_date,
requester)`

Before writing the proposal, it computes the **estimated margin impact**
for every product — current price vs. discounted price, margin
percentage before and after — using each product's real recent sales
velocity and cost. This is what satisfies Workflow D's "check margin
after discount" step: the human approver sees the consequence of the
discount up front, in the same payload they're being asked to approve,
not just the raw request.

## `propose_inventory_alert(variant_id, threshold, requester)`

Simpler: proposes a new reorder-alert threshold for one variant. Records
the *current* threshold alongside the proposed one, so an approver can
see exactly what's changing.

## The boundary line, made literal

Everything **above** this comment in the file is in `TOOL_REGISTRY`
(`tools/schemas.py`) — the model can call it. Everything **below** —
`list_approval_requests`, `decide_approval`, `execute_approval` — is
deliberately **not** registered. Only `app/main.py`'s HTTP endpoints call
those three, and only after an authenticated human action. The model
physically cannot reach the "approve" or "execute" code paths through its
own tool-calling loop, no matter what it's asked to do.

## `execute_approval(request_id)` — the idempotency guarantee

Checks `executed_at` before doing anything. If it's already set, this
call is a safe no-op: it returns `{"status": "already_executed", ...}`
instead of applying the change a second time. This is exactly the
brief's "prevent duplicate writes with idempotency" and "execute an
approved write no more than once" requirements — and it's checked
*inside the database transaction*, not just hoped for by the caller not
double-clicking a button.

## How this connects to the rest of the project

`tools/schemas.py` registers only the two `propose_*` functions, each
requiring the `manager` role minimum. `app/main.py`'s `/approvals/*`
endpoints call `decide_approval` and `execute_approval` directly, gated
by `_require_manager()` — a human acting through the API, never the
model's tool loop.
