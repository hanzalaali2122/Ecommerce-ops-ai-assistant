# `app/agent.py` — explained

**What it is:** the real tool-calling loop — the brief's "execution
pattern" made concrete, talking to Gemini through its OpenAI-compatible
Chat Completions endpoint.

## Why the `openai` Python package, for a Gemini-powered project?

Google's Gemini API exposes an OpenAI-compatible Chat Completions
endpoint (the brief's own stack requirement: *"Model: Gemini through the
Chat Completions compatibility endpoint"*). That means the function-
calling shape — `messages`, `tools`, `tool_calls`, `role: "tool"`
messages tagged with a `tool_call_id` — is the familiar OpenAI one. This
file just points the standard `openai` client at Google's base URL
(`GEMINI_BASE_URL`) instead of OpenAI's, so there's nothing
Gemini-specific to learn beyond that one base-URL swap.

## The loop, step by step (`run_investigation`)

```
1. Build messages: [system prompt, user's question]
2. Loop, up to MAX_ROUNDS times:
     a. Call the model with the full tool catalog.
     b. No tool_calls in the reply?  -> done, return the final answer.
     c. Has tool_calls?
          For EACH call:
            - Not in TOOL_REGISTRY?         -> refuse, log as "blocked"
            - Role doesn't meet requires_role? -> refuse, log as "blocked"
            - Otherwise: run it, catching ToolValidationError/TypeError/
              any Exception so ONE bad call never crashes the whole
              request -- log the outcome either way.
          Feed every result back as a 'tool' role message, tagged with
          its tool_call_id (so the model knows which result answers
          which call -- essential once it's made more than one call in
          a round).
          Go back to (a).
3. Hit MAX_ROUNDS without a final answer?
     -> stop anyway, say so honestly, return what was found so far.
```

Two execution limits are enforced here, directly matching the brief's
"bound rounds... bound tool calls": `MAX_ROUNDS = 6` (how many times the
model gets to call the API at all) and `MAX_TOOL_CALLS_PER_REQUEST = 20`
(a hard ceiling on total tool invocations across the whole investigation,
checked inside `_execute_tool_call` before a call that would exceed it is
even attempted).

## The system prompt's rules, and why each one exists

- *"You never guess numbers, you call a tool for anything numeric"* —
  the whole point of function calling: the model reasons, the tools
  compute.
- *"Distinguish association from causation"* — directly satisfies the
  brief's Workflow A requirement that a stockout or refund spike can
  "explain part of" a decline but can't be claimed to have "caused every
  lost sale."
- *"State the exact dates you used"* for ambiguous ranges like "last
  week" — so a person can catch and correct a wrong guess, rather than
  silently getting an answer to a slightly different question than they
  asked.
- *"propose_discount/propose_inventory_alert only ever create a
  proposal"* — reinforces, at the prompt level, the structural boundary
  already enforced in `tools/approvals.py` and `tools/schemas.py`
  (belt-and-suspenders: even if the model misunderstands, the code
  itself cannot let it approve its own proposal).

## `_execute_tool_call` — one call, start to finish

Allowlist check → role check → execute (catching validation errors,
`TypeError` for malformed arguments, and any other exception as a
last-resort guard) → log to `tool_runs` → build an `evidence` entry. This
function is the single choke point every tool call passes through, which
is what guarantees nothing the model calls ever runs un-logged or
un-checked.

## `_collect_data` and `_public_evidence`

`_collect_data` builds the response's `data` block keyed by tool name
(suffixing repeated calls to the same tool, e.g.
`get_product_performance_2`, so a second call never silently overwrites
the first). `_public_evidence` strips the full result out of each
evidence entry before it goes in the API response — the full result
already lives in `data` and in the `tool_runs` table, so repeating it a
third time in `evidence` would just be redundant weight on every
response.

## What this file deliberately does NOT do

It contains zero business-logic validation of its own — no date-range
checking, no percentage bounds. That all lives in `tools/validation.py`,
inside each tool function, so the same rules apply identically whether a
function is called from this real Gemini loop, from
`app/mock_agent.py`'s rule-based dispatcher, or directly from a test.

## How this connects to the rest of the project

`app/main.py`'s `/chat` endpoint imports `run_investigation` from here
only when `GEMINI_API_KEY` is set in the environment; otherwise it uses
`app/mock_agent.py` instead, with an identical response shape either way.
