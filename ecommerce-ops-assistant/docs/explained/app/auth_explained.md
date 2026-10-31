# `app/auth.py` — explained

**What it is:** the smallest file in `app/`, and intentionally so. It's a
stand-in for real authentication, not a production login system.

## What it actually does

```python
def get_current_role(x_user_role: str = Header(default="analyst")) -> str:
    ...
def get_current_user(x_user_id: str = Header(default="demo-user")) -> str:
    ...
```

Reads a role and a user ID straight out of HTTP request headers
(`X-User-Role`, `X-User-Id`), defaulting to `"analyst"` / `"demo-user"`
if absent. `get_current_role` rejects anything outside
`{"analyst", "support", "manager"}` with a 400 error.

## Why this is fine for this project

The brief's requirement is *"Access control: separate analyst, support,
and manager permissions"* — and the point being demonstrated is that
**the tools enforce roles** (`tools/schemas.py`'s `role_allows`, checked
inside `app/agent.py` / `app/mock_agent.py` before any tool runs), not
that this project ships a production identity system. A real deployment
would replace `get_current_role` with something that decodes a verified
session token or JWT and looks the person's role up from a real `users`
table — but that's a separate, orthogonal piece of engineering from "does
the access-control boundary actually get enforced once we know who
someone is," which is what this project is demonstrating.

## How this connects to the rest of the project

FastAPI's `Depends(get_current_role)` / `Depends(get_current_user)` wire
these two functions into every endpoint in `app/main.py` that needs to
know who's asking — the `/chat` endpoint, the approval endpoints, and the
direct `/tools/propose_*` endpoints all resolve the caller's role this
way before doing anything with it.
