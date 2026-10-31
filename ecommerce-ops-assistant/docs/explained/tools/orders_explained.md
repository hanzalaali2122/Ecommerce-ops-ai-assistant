# `tools/orders.py` — explained

**What it is:** the two tools behind Workflow C ("check order 10452...")
— looking up a single order, and summarizing a single customer's history.

## `get_order(order_id, requesting_role="support")`

Fetches one order's header (status, totals, currency), every line item
(joined to the product title so the caller doesn't need a second lookup),
and any refunds against it. Returns `{"error": "not_found", ...}` for an
unknown ID — this is the brief's "report not found without inventing
records" test case, satisfied directly by the code rather than relying
on the model to behave.

**The access-control detail:** if `requesting_role` is `"analyst"`, the
returned `customer_id` is replaced with the literal string
`"[redacted: analyst role]"`. This is a small, concrete example of the
brief's "enforce the signed-in user's access" requirement — an analyst
can see that an order exists and what it's worth, but not which customer
placed it. This check happens *inside the tool function itself*, not
just as a prompt instruction to the model, because the brief is explicit
that sensitive-data access has to be enforced in code.

## `get_customer_summary(customer_id, requesting_role="support")`

One customer's purchase history: total completed orders, lifetime
revenue, average order value, and their 10 most recent orders. The same
role-based redaction applies here, but to `email` instead of
`customer_id` (the ID is the point of the lookup; the email is the PII
worth protecting from a lower-privilege role).

## Why `requesting_role` is a plain function argument, not read from a
global

Keeping access control as an explicit parameter (rather than, say, a
thread-local or a global "current user") means these functions are
trivially testable — `tests/test_tools.py` just calls
`get_order(oid, requesting_role="analyst")` directly, no web server or
auth middleware needed to prove the redaction works.

## How this connects to the rest of the project

`app/auth.py` resolves the caller's real role from an HTTP header;
`app/agent.py` and `app/mock_agent.py` both thread that role through into
every tool call, including these two.
