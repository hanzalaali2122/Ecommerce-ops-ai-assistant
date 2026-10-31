# `tools/schemas.py` — explained

**What it is:** the allowlist. The single source of truth for which
Python functions the AI model is ever permitted to call, and what their
arguments look like. This is what the brief means by "execute only
allowlisted functions" — `app/agent.py` imports `TOOL_REGISTRY` from
here and refuses to run anything not listed in it.

## The shape of one registry entry

```python
"get_sales_summary": {
    "function": sales.get_sales_summary,     # the real Python callable
    "requires_role": "analyst",               # minimum role to call it
    "schema": { ... JSON Schema for Gemini ... },
},
```

Three things, bundled together on purpose: the actual function to run,
the access-control rule for running it, and the description Gemini needs
to decide *when* to call it. Keeping these three together means you
can't update one without seeing the other two right next to it — e.g.
you can't loosen a tool's role requirement without also seeing its
description, which is a natural prompt to ask "should an analyst really
be able to do this?"

## `role_allows(role, requires_role)`

A deliberately simple total order: `manager (2) > support (1) > analyst
(0)`. A higher-ranked role can do everything a lower-ranked role can.
This isn't a real permissions matrix (no per-resource grants, no custom
roles) — it's just enough to demonstrate and test the brief's "separate
analyst, support, manager permissions" requirement without over-building
an identity system for a project whose point is the AI tool-calling
pattern, not access control itself.

## What's notably absent from this registry

`execute_approval`, `decide_approval`, and `list_approval_requests` (all
defined in `tools/approvals.py`) are **not** here. That omission is the
brief's "the model cannot approve its own request" rule made structural:
there is no code path by which the model's tool-calling loop can reach
those three functions, because they were never registered as callable
tools in the first place. Only `app/main.py`'s HTTP endpoints — reachable
only by an authenticated human action — call them directly.

## `gemini_tool_declarations()`

Just extracts the `"schema"` half of every registry entry into the list
shape the Gemini API's `tools` parameter expects. The model sees these
schemas; it never sees the registry's Python function references or role
requirements directly — those are enforced server-side, after the model
has already decided to call something, by `app/agent.py`.

## How this connects to the rest of the project

`app/agent.py`'s tool-calling loop and `app/mock_agent.py`'s rule-based
dispatcher both import `TOOL_REGISTRY` and `role_allows` from here and
treat them identically — neither "which tools exist" nor "who can call
them" differs depending on which agent implementation answers a request.
