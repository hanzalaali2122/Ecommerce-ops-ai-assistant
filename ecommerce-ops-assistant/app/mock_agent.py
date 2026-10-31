"""
app/mock_agent.py
--------------------------------------------------------------------------
WHY THIS FILE EXISTS
app/agent.py needs a real GEMINI_API_KEY to do anything (it calls out to
Google's Gemini API). Until you add one, the FastAPI app would otherwise
be untestable end to end. This file is a small, rule-based stand-in: it
recognizes a handful of question *patterns* (not real language
understanding) and calls the exact same real tool functions and
TOOL_REGISTRY that app/agent.py uses, against the exact same real
database. Nothing about the data or the tools is fake here -- only the
"which tool should I call" decision is hard-coded instead of made by an
LLM.

app/main.py uses this automatically whenever GEMINI_API_KEY is not set, so
you can run the whole project -- database, tools, approval workflow,
frontend -- right now, and swap in real Gemini reasoning later by just
setting the environment variable. The response shape (answer, data,
evidence, proposed_actions, warnings, request_id) is identical either way,
so the frontend and API consumers never need to know which one answered.

This deliberately only covers variations of the four workflows in the
brief. Anything it doesn't recognize gets an honest "I don't understand
this yet; this is the rule-based fallback, not the full Gemini loop"
message rather than a wrong guess.
"""

import re
import uuid

from metrics import last_n_complete_days, previous_n_complete_days
from tools.schemas import TOOL_REGISTRY, role_allows
from tools.audit import log_tool_run as _log_tool_run


def _call(request_id, tool_name, kwargs, role, evidence, data):
    """Runs one tool call the same way app/agent.py does: allowlist +
    role check, execute, log to tool_runs, append to evidence, and store
    the result under `data[tool_name]` (so the structured response shape
    matches the real Gemini-backed agent exactly)."""
    entry = TOOL_REGISTRY[tool_name]
    if not role_allows(role, entry["requires_role"]):
        result = {"error": "forbidden",
                  "message": f"Role {role!r} cannot call {tool_name!r}."}
        run_id = _log_tool_run(request_id, tool_name, kwargs, result, "blocked", 0)
        evidence.append({"tool": tool_name, "arguments": kwargs, "status": "blocked",
                          "duration_ms": 0, "result_id": run_id})
        return result

    result = entry["function"](**kwargs)
    run_id = _log_tool_run(request_id, tool_name, kwargs, result, "success", 0)
    evidence.append({"tool": tool_name, "arguments": kwargs, "status": "success",
                      "duration_ms": 0, "result_id": run_id})
    key = tool_name if tool_name not in data else f"{tool_name}_{sum(1 for e in evidence if e['tool'] == tool_name)}"
    data[key] = result
    return result


def run_investigation_mock(question: str, role: str = "analyst", requester: str = "web-user") -> dict:
    request_id = str(uuid.uuid4())
    q = question.lower()
    evidence = []
    data = {}
    warnings = ["Answered by the rule-based mock agent (no GEMINI_API_KEY set) -- "
                "set GEMINI_API_KEY to use real Gemini reasoning instead."]

    def log(tool_name, kwargs):
        return _call(request_id, tool_name, kwargs, role, evidence, data)

    def finish(answer, proposed_actions=None):
        return {
            "answer": answer, "data": data, "evidence": evidence,
            "proposed_actions": proposed_actions or [],
            "warnings": warnings, "request_id": request_id,
        }

    # --- Workflow A: sales decline investigation -------------------------
    if any(k in q for k in ["sales drop", "revenue drop", "why did sales", "compare",
                             "decline", "last seven", "last 7"]):
        current = last_n_complete_days(7)
        previous = previous_n_complete_days(7)
        cmp_result = log("compare_sales_periods", {
            "current_start": current.start_date.isoformat(), "current_end": current.end_date.isoformat(),
            "previous_start": previous.start_date.isoformat(), "previous_end": previous.end_date.isoformat(),
        })
        perf_current = log("get_product_performance", {
            "start_date": current.start_date.isoformat(), "end_date": current.end_date.isoformat(),
            "sort_by": "revenue", "limit": 5,
        })
        perf_previous = log("get_product_performance", {
            "start_date": previous.start_date.isoformat(), "end_date": previous.end_date.isoformat(),
            "sort_by": "revenue", "limit": 5,
        })
        refund_summary = log("get_refund_summary", {
            "start_date": current.start_date.isoformat(), "end_date": current.end_date.isoformat(),
        })

        change = cmp_result.get("revenue_change", 0)
        direction = "rose" if change >= 0 else "fell"
        top_current = [p["title"] for p in perf_current.get("products", [])[:3]]
        top_previous = [p["title"] for p in perf_previous.get("products", [])[:3]]
        refund_total = sum(b["refund_amount"] for b in refund_summary.get("breakdown", []))

        answer = (
            f"Revenue {direction} by {abs(change):.2f} "
            f"({cmp_result.get('revenue_change_pct', 0) * 100:.1f}%) comparing "
            f"{current.start_date} to {current.end_date} against the prior 7 days "
            f"({previous.start_date} to {previous.end_date}).\n"
            f"Top revenue products this period: {', '.join(top_current) or 'none'}.\n"
            f"Top revenue products previous period: {', '.join(top_previous) or 'none'}.\n"
            f"Refunds in the current window totalled {refund_total:.2f}.\n"
            f"Note: these products and refunds are associated with the change -- this "
            f"does not prove any single factor caused all of it."
        )
        return finish(answer)

    # --- Workflow B: replenishment planning ------------------------------
    if any(k in q for k in ["run out", "reorder", "restock", "replenish", "stockout", "stock out"]):
        risk = log("get_stockout_risk", {"lookback_days": 14, "limit": 10})
        at_risk = risk.get("at_risk_within_14_days", [])
        reorder_lines = []
        for item in at_risk[:5]:
            r = log("calculate_reorder_quantity", {
                "variant_id": item["variant_id"], "target_coverage_days": 14,
            })
            reorder_lines.append(f"{item['title']} ({item['variant_id']}): "
                                  f"suggest reordering {r.get('suggested_reorder', 'n/a')} units")
        answer = (
            f"{len(at_risk)} variant(s) are estimated to run out within 14 days.\n" +
            ("\n".join(reorder_lines) if reorder_lines else "None currently at risk.") +
            "\nThese are starting estimates based on recent sales velocity only; they do "
            "not account for seasonality or supplier lead times."
        )
        return finish(answer)

    # --- Workflow C: investigate one order --------------------------------
    order_match = re.search(r"\border\s*#?\s*(\w+)", q) or re.search(r"\b(\d{5,7}|C\d{5,7})\b", question)
    if order_match or "order" in q:
        order_id = order_match.group(1) if order_match else None
        if not order_id:
            return finish("Which order id should I check? Please include a specific order number.")
        result = log("get_order", {"order_id": order_id})
        if result.get("error") == "forbidden":
            answer = result["message"]
        elif result.get("error"):
            answer = f"Order {order_id} was not found. I'm not inventing a record for it."
        else:
            o = result["order"]
            n_items = len(result["items"])
            n_refunds = len(result["refunds"])
            answer = (
                f"Order {order_id} is {o['status']}, placed {o['order_date']}, "
                f"total {o['currency']} {o['total']:.2f}, with {n_items} line item(s) "
                f"and {n_refunds} refund(s) against it."
            )
        return finish(answer)

    # --- Workflow D: propose a discount ------------------------------------
    if "discount" in q or "promo" in q:
        return finish(
            "The rule-based mock agent can't safely parse a free-text discount "
            "request (which products, what percentage, which dates) -- that needs "
            "real language understanding. Set GEMINI_API_KEY to enable this workflow "
            "through chat, or call POST /tools/propose_discount directly."
        )

    return finish(
        "The rule-based mock agent (no GEMINI_API_KEY set) only recognizes "
        "questions shaped like the four brief workflows: a sales-decline "
        "investigation, a restock/replenishment question, 'check order <id>', "
        "or a discount request. Try rephrasing, or set GEMINI_API_KEY to enable "
        "full Gemini reasoning over all tools."
    )
