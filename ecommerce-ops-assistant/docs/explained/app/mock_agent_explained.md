# `app/mock_agent.py` — explained

**What it is:** a rule-based stand-in for `app/agent.py`, used
automatically whenever `GEMINI_API_KEY` isn't set. It lets the whole
project — database, tools, approval workflow, frontend — run and be
demonstrated with zero API key and zero real language understanding.

## The key honesty principle

Nothing about the *data* or the *tools* is fake here. This file calls the
exact same real functions from `TOOL_REGISTRY` (`tools/schemas.py`)
against the exact same real database that `app/agent.py` would call. The
**only** thing that's faked is the "which tool should I call for this
question" decision — instead of an LLM reasoning about it, this file
matches the question against a few keyword patterns with regular
expressions.

## How it recognizes a question

```python
if any(k in q for k in ["sales drop", "revenue drop", "why did sales", ...]):
    # Workflow A
if any(k in q for k in ["run out", "reorder", "restock", ...]):
    # Workflow B
if order_match or "order" in q:
    # Workflow C
if "discount" in q or "promo" in q:
    # explains it can't safely do this one (see below)
```

Each matched branch calls the real tool functions in the same sequence a
person following the brief's workflow steps would: e.g. for Workflow A,
it calls `compare_sales_periods`, then `get_product_performance` for
*both* the current and previous window, then `get_refund_summary` — and
builds a plain-English answer from those real results, including the
brief's required caution: *"these products and refunds are associated
with the change — this does not prove any single factor caused all of
it."*

## Why Workflow D (propose a discount) is deliberately refused here

Preparing a discount needs to parse free text into specific structured
arguments — which products, what percentage, which dates — out of
something like "prepare a 10% discount for slow-selling jackets for three
days." That's real language understanding, which a keyword-matching
fallback genuinely cannot do safely. Rather than guess badly (and risk
proposing a discount on the wrong products), this file is honest about
the gap: it tells the caller to either set `GEMINI_API_KEY` for the real
loop, or call `POST /tools/propose_discount` directly with explicit
arguments.

## Why a response here looks identical to a real Gemini response

Both this file and `app/agent.py` return the exact same shape: `answer,
data, evidence, proposed_actions, warnings, request_id`. `app/main.py`
picks between them based solely on whether `GEMINI_API_KEY` is set — the
frontend and any other API consumer never need to know or care which one
actually answered.

## How this connects to the rest of the project

`app/main.py`'s `/chat` endpoint imports and calls
`run_investigation_mock` whenever `GEMINI_API_KEY` is absent from the
environment.
