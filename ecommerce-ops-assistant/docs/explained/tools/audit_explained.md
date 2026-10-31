# `tools/audit.py` — explained

**What it is:** a tiny, single-purpose helper — write one row to the
`tool_runs` table and return its ID. Thirty lines, but it's the thread
that makes the "Investigation view" in the brief possible at all.

## What `log_tool_run(...)` does

Every single tool call the assistant makes — whether it's a harmless
`get_sales_summary` read or a `propose_discount` write — gets exactly one
row here: which tool, what arguments, what came back (truncated to 2,000
characters so a huge result never bloats the log table), whether it
succeeded/errored/was blocked, how long it took, and when it started.
The function returns that row's `run_id`.

That `run_id` becomes `evidence[].result_id` in the brief's structured
API response shape — it's the exact thread that lets a person go from
"the assistant said revenue fell 12%" to the precise tool call and raw
result that claim came from, which is the entire point of the
Investigation view: nothing in an answer should be untraceable.

## Why this lives in its own file instead of inside `app/agent.py`

Both the real Gemini-backed loop (`app/agent.py`) and the rule-based
fallback (`app/mock_agent.py`) need to log tool calls identically. But
`app/agent.py` imports the `openai` package at the top of the file (it
needs it to talk to Gemini's OpenAI-compatible endpoint) — if the
audit-logging helper lived inside `app/agent.py`, then `app/mock_agent.py`
would transitively require the `openai` package to be installed even
though it never calls any model. That would defeat the entire purpose of
having a "mock mode" that runs with nothing but the Python standard
library plus this project's own code. Keeping `tools/audit.py`
dependency-free (it only imports `json`, `time`, `uuid`, and
`tools.db`) keeps that promise.

## How this connects to the rest of the project

`app/agent.py` and `app/mock_agent.py` both call `log_tool_run` for
*every* tool invocation attempt, allowed or not. `app/main.py`'s
`/investigations/{request_id}` endpoint reads the `tool_runs` table this
function writes to, filtered by `request_id`.
