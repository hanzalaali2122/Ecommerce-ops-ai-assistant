"""
app/auth.py
--------------------------------------------------------------------------
A deliberately simple stand-in for real authentication. The brief asks for
"Access control: Separate analyst, support, and manager permissions" --
the point being demonstrated is that the *tools* enforce roles
(tools/schemas.py's role_allows, checked inside app/agent.py and
app/mock_agent.py before any tool runs), not that this project ships a
production login system.

In a real deployment, get_current_role would decode a verified session
token / JWT and look up the person's role from a users table. Here, it
just reads a header the frontend sets from a dropdown, which is enough to
demonstrate and test the access-control boundary (e.g. "Analyst refund
request -> Deny the unauthorized action" from the brief's evaluation
table) without building a full identity system.
"""

from fastapi import Header, HTTPException

VALID_ROLES = {"analyst", "support", "manager"}


def get_current_role(x_user_role: str = Header(default="analyst")) -> str:
    role = (x_user_role or "analyst").lower()
    if role not in VALID_ROLES:
        raise HTTPException(status_code=400, detail=f"Unknown role {role!r}. Use one of {sorted(VALID_ROLES)}.")
    return role


def get_current_user(x_user_id: str = Header(default="demo-user")) -> str:
    return x_user_id or "demo-user"
