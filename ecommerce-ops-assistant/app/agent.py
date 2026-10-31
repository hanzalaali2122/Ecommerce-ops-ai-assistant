"""
app/agent.py
--------------------------------------------------------------------------
This file is the "execution pattern" the brief describes:

    "Send the question and relevant schemas to Gemini. Validate every
    emitted call, execute only allowlisted functions, and return results
    with their tool call IDs. Continue until the model can answer or an
    execution limit is reached."

HOW IT TALKS TO GEMINI
Gemini exposes an OpenAI-compatible "Chat Completions" endpoint (the
brief's "Model: Gemini through the Chat Completions compatibility
endpoint"), so this file uses the standard `openai` Python package, just
pointed at Google's base URL instead of OpenAI's. That means the function-
calling shape (messages, tools, tool_calls, tool role messages) is the
familiar OpenAI one -- nothing Gemini-specific to learn here.

THE LOOP, STEP BY STEP
  1. Build the message list: a system prompt explaining the assistant's
     job and constraints, plus the conversation so far.
  2. Call the model with the full tool catalog (tools/schemas.py).
  3. If the model's reply contains tool_calls:
       a. For EACH call: look it up in TOOL_REGISTRY. If it's not there,
          refuse it (never silently ignore -- the model needs to see the
          refusal to recover). If it IS there, check the caller's role
          against requires_role. If allowed, validate+run the Python
          function (tools/validation.py does the argument checking inside
          each function). Log every attempt -- allowed, blocked, or
          errored -- to tool_runs.
       b. Feed every result back as a 'tool' role message, each tagged
          with its tool_call_id, exactly as the brief asks
          ("return results with their tool call IDs").
       c. Go back to step 2.
  4. If the reply has no tool_calls, that's the final answer -- stop.
  5. If MAX_ROUNDS is hit first, stop anyway and say so, rather than
     looping forever on a confused model (the brief's "Execution limits:
     Bound rounds, tool calls, returned rows, and total runtime").

WHAT THIS FILE DOES NOT DO
It does not decide what counts as a valid date range, a valid discount
percentage, etc. -- that validation lives in tools/validation.py, inside
each tool function, so it applies identically whether the function is
called from here, from a test, or (hypothetically) from a different
front end entirely.
"""

import json
import os
import time
import uuid

from openai import OpenAI

from tools.schemas import TOOL_REGISTRY, role_allows, gemini_tool_declarations
from tools.validation import ToolValidationError
from tools.audit import log_tool_run as _log_tool_run

MAX_ROUNDS = 6                 # brief: "Bound rounds"
MAX_TOOL_CALLS_PER_REQUEST = 20  # brief: "Bound ... tool calls"

GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash")

SYSTEM_PROMPT = """You are an ecommerce operations analyst assistant for a \
Shopify-style store. You investigate sales, inventory, customers, and \
orders using the tools provided -- you never guess numbers, you call a \
tool for anything numeric.

Rules you must follow:
- Only call the tools you have been given. Never invent data.
- When asked "why" something happened (e.g. a sales drop), distinguish \
association from causation: a stockout or refund spike can EXPLAIN PART \
of a change, but you cannot claim it CAUSED every lost sale. Say so \
explicitly.
- If a date range is ambiguous ("last week"), state the exact dates you \
used so the person can correct you if you guessed wrong.
- propose_discount and propose_inventory_alert only ever CREATE A \
PROPOSAL for a human to approve -- they never make anything live. Always \
tell the person this clearly.
- If a tool call is blocked (e.g. for a permissions reason) or a \
dependency fails, say so plainly instead of making up a workaround.
- If an order, customer, or product is not found, say it was not found. \
Do not invent a plausible-looking record.
- Keep answers concise and grounded only in what the tools returned.
"""


def _client() -> OpenAI:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "GEMINI_API_KEY is not set. Add it to a .env file or your shell "
            "environment before starting the server. See README.md."
        )
    return OpenAI(api_key=api_key, base_url=GEMINI_BASE_URL)


def _execute_tool_call(tool_call, role: str, request_id: str, total_calls: int):
    """
    Runs one model-requested tool call end to end: allowlist check, role
    check, argument parsing, execution, logging. Returns (result_dict,
    evidence_entry) -- evidence_entry is None if the call was blocked
    before it could produce real evidence.
    """
    name = tool_call.function.name
    try:
        arguments = json.loads(tool_call.function.arguments or "{}")
    except json.JSONDecodeError:
        arguments = {}

    start = time.time()

    if total_calls > MAX_TOOL_CALLS_PER_REQUEST:
        result = {"error": "execution_limit_reached",
                  "message": f"More than {MAX_TOOL_CALLS_PER_REQUEST} tool calls were "
                             f"requested in this investigation; stopping here."}
        run_id = _log_tool_run(request_id, name, arguments, result, "blocked", 0)
        return result, {"tool": name, "arguments": arguments, "status": "blocked",
                         "duration_ms": 0, "result_id": run_id}

    entry = TOOL_REGISTRY.get(name)
    if entry is None:
        result = {"error": "unknown_tool", "message": f"{name!r} is not an allowlisted tool."}
        run_id = _log_tool_run(request_id, name, arguments, result, "blocked", 0)
        return result, {"tool": name, "arguments": arguments, "status": "blocked",
                         "duration_ms": 0, "result_id": run_id}

    if not role_allows(role, entry["requires_role"]):
        result = {
            "error": "forbidden",
            "message": f"Role {role!r} is not permitted to call {name!r} "
                       f"(requires at least {entry['requires_role']!r}).",
        }
        run_id = _log_tool_run(request_id, name, arguments, result, "blocked", 0)
        return result, {"tool": name, "arguments": arguments, "status": "blocked",
                         "duration_ms": 0, "result_id": run_id}

    try:
        result = entry["function"](**arguments)
        status = "success"
    except ToolValidationError as exc:
        result = {"error": "validation_error", "message": str(exc)}
        status = "error"
    except TypeError as exc:
        # Wrong/missing arguments from the model -- surface it as a tool
        # error the model can see and correct, not a crash.
        result = {"error": "bad_arguments", "message": str(exc)}
        status = "error"
    except Exception as exc:  # last-resort guard so one bad call never kills the request
        result = {"error": "internal_error", "message": f"{exc.__class__.__name__}: {exc}"}
        status = "error"

    duration_ms = int((time.time() - start) * 1000)
    run_id = _log_tool_run(request_id, name, arguments, result, status, duration_ms)

    evidence_entry = {"tool": name, "arguments": arguments, "status": status,
                       "duration_ms": duration_ms, "result_id": run_id,
                       "result": result if status == "success" else None}
    return result, evidence_entry


def run_investigation(question: str, role: str = "analyst", requester: str = "web-user") -> dict:
    """
    The main entry point: takes a natural-language question, runs the
    Gemini tool-calling loop, and returns the brief's structured response
    shape: answer, data, evidence, proposed_actions, warnings, request_id.
    """
    request_id = str(uuid.uuid4())
    client = _client()

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": question},
    ]
    tools = [{"type": "function", "function": decl} for decl in gemini_tool_declarations()]

    evidence = []
    warnings = []
    total_calls = 0

    for round_number in range(1, MAX_ROUNDS + 1):
        response = client.chat.completions.create(
            model=GEMINI_MODEL,
            messages=messages,
            tools=tools,
        )
        choice = response.choices[0]
        message = choice.message

        if not message.tool_calls:
            # The model is ready to answer -- this is the normal exit.
            return {
                "answer": message.content or "",
                "data": _collect_data(evidence),
                "evidence": [_public_evidence(e) for e in evidence],
                "proposed_actions": [e["result"] for e in evidence if e["tool"] in
                                      ("propose_discount", "propose_inventory_alert")
                                      and e["result"]],
                "warnings": warnings,
                "request_id": request_id,
                "rounds_used": round_number,
            }

        # The model wants to call one or more tools. Record the assistant
        # message (including its tool_calls) before the tool results, as
        # the brief asks: "Preserve complete assistant tool messages."
        messages.append({
            "role": "assistant",
            "content": message.content,
            "tool_calls": [
                {
                    "id": tc.id, "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                }
                for tc in message.tool_calls
            ],
        })

        for tool_call in message.tool_calls:
            total_calls += 1
            result, evidence_entry = _execute_tool_call(tool_call, role, request_id, total_calls)
            if evidence_entry:
                evidence.append(evidence_entry)
            if isinstance(result, dict) and result.get("error"):
                warnings.append(f"{tool_call.function.name}: {result.get('message', result['error'])}")

            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": json.dumps(result),
            })

    # Execution limit reached without a final answer.
    warnings.append(f"Stopped after {MAX_ROUNDS} rounds without a final answer.")
    return {
        "answer": "I wasn't able to finish this investigation within the allowed "
                  "number of steps. Here is what I found so far; consider narrowing "
                  "the question.",
        "data": _collect_data(evidence),
        "evidence": [_public_evidence(e) for e in evidence],
        "proposed_actions": [e["result"] for e in evidence if e["tool"] in
                              ("propose_discount", "propose_inventory_alert")
                              and e["result"]],
        "warnings": warnings,
        "request_id": request_id,
        "rounds_used": MAX_ROUNDS,
    }


def _collect_data(evidence: list[dict]) -> dict:
    """Builds the structured `data` block from every successful tool call's
    result, keyed by tool name. If the same tool was called more than once
    (e.g. get_product_performance for two different windows), later calls
    are suffixed so nothing is silently overwritten."""
    data = {}
    counts = {}
    for e in evidence:
        if e["status"] != "success" or e["result"] is None:
            continue
        counts[e["tool"]] = counts.get(e["tool"], 0) + 1
        key = e["tool"] if counts[e["tool"]] == 1 else f"{e['tool']}_{counts[e['tool']]}"
        data[key] = e["result"]
    return data


def _public_evidence(e: dict) -> dict:
    """The evidence list in the API response should be a lightweight index
    (tool, arguments, status, timing, result_id) -- the full result lives
    in `data` and in the tool_runs table, not duplicated in every evidence
    entry."""
    return {k: v for k, v in e.items() if k != "result"}
