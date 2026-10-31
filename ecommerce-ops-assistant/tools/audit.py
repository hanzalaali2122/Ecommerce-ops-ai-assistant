"""
tools/audit.py
--------------------------------------------------------------------------
A tiny shared helper: write one row to tool_runs and return its run_id.

This lives in its own file (rather than inside app/agent.py) on purpose:
both the real Gemini-backed agent (app/agent.py) and the rule-based
fallback (app/mock_agent.py) need to log tool calls, but app/agent.py
imports the `openai` package at module load time. If this helper lived in
app/agent.py, app/mock_agent.py would transitively require `openai` to be
installed even though it never calls Gemini -- exactly the kind of
accidental coupling that makes a "mock mode" useless for its own purpose
(running without the real dependency). Keeping the audit-log writer
dependency-free means the mock agent, and this file's own tests, work
with nothing but the Python standard library plus this project's own code.
"""

import json
import time
import uuid

from tools.db import get_connection


def log_tool_run(request_id, tool_name, arguments, result_summary, status, duration_ms):
    """Writes one row to tool_runs and returns its run_id, which becomes
    evidence[].result_id in the structured API response -- the thread that
    lets a person go from 'the assistant said revenue fell' to the exact
    tool call and raw result that claim came from (the Investigation
    view's whole purpose)."""
    run_id = str(uuid.uuid4())
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO tool_runs (run_id, request_id, tool_name, arguments, "
            "result_summary, status, duration_ms, started_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                run_id, request_id, tool_name,
                json.dumps(arguments)[:2000],
                json.dumps(result_summary)[:2000] if result_summary is not None else None,
                status, duration_ms, time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return run_id
