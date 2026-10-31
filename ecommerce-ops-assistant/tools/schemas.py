"""
tools/schemas.py
--------------------------------------------------------------------------
THE ALLOWLIST. This file is the single source of truth for which Python
functions the model is ever allowed to call, and what their arguments look
like. app/agent.py (the Gemini tool-calling loop) imports TOOL_REGISTRY
from here and refuses to run anything not listed in it -- this is what the
brief means by "execute only allowlisted functions".

Each entry has:
  - "function": the actual Python callable (imported from tools/*.py)
  - "schema": the JSON schema describing the tool to Gemini, in the
    "function declaration" shape the Gemini API's function-calling feature
    expects (name, description, parameters as a JSON Schema object).
  - "requires_role": the minimum role (see app/auth.py) allowed to call
    this tool at all. propose_discount and propose_inventory_alert require
    'manager' or 'support'; a plain 'analyst' role is blocked before the
    function is ever invoked, which is how this project satisfies the
    brief's "Analyst refund request -> Deny the unauthorized action" and
    "Discount without approval -> Keep the action as a proposal" cases
    (the second is also enforced by propose_discount only ever creating a
    pending row, never a live discount).

Note that propose_discount / propose_inventory_alert are in this registry
(the model CAN call them -- that's how Workflow D works), but
execute_approval, decide_approval, and list_approval_requests are NOT.
Those three are only reachable through app/main.py's HTTP endpoints, which
require an authenticated human action, never a model tool call. This is
the "model cannot approve its own request" boundary from the brief.
"""

from tools import catalog, orders, sales, inventory, external, approvals

TOOL_REGISTRY = {
    "search_products": {
        "function": catalog.search_products,
        "requires_role": "analyst",
        "schema": {
            "name": "search_products",
            "description": "Find products by a text search over their title, optionally filtered to one category.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Text to search for in product titles."},
                    "category": {"type": "string", "description": "Optional category to filter by."},
                    "limit": {"type": "integer", "description": "Max results to return (default 20, max 200)."},
                },
                "required": ["query"],
            },
        },
    },
    "get_product_details": {
        "function": catalog.get_product_details,
        "requires_role": "analyst",
        "schema": {
            "name": "get_product_details",
            "description": "Get full details (and all variants) for one product by its product_id.",
            "parameters": {
                "type": "object",
                "properties": {"product_id": {"type": "string"}},
                "required": ["product_id"],
            },
        },
    },
    "get_inventory": {
        "function": catalog.get_inventory,
        "requires_role": "analyst",
        "schema": {
            "name": "get_inventory",
            "description": "Get current available stock and reorder threshold for one product variant.",
            "parameters": {
                "type": "object",
                "properties": {"variant_id": {"type": "string"}},
                "required": ["variant_id"],
            },
        },
    },
    "get_order": {
        "function": orders.get_order,
        "requires_role": "support",
        "schema": {
            "name": "get_order",
            "description": "Get one order's status, line items, and any refunds against it, by order_id.",
            "parameters": {
                "type": "object",
                "properties": {"order_id": {"type": "string"}},
                "required": ["order_id"],
            },
        },
    },
    "get_customer_summary": {
        "function": orders.get_customer_summary,
        "requires_role": "support",
        "schema": {
            "name": "get_customer_summary",
            "description": "Summarize one customer's purchase history: order count, lifetime revenue, AOV, recent orders.",
            "parameters": {
                "type": "object",
                "properties": {"customer_id": {"type": "string"}},
                "required": ["customer_id"],
            },
        },
    },
    "get_sales_summary": {
        "function": sales.get_sales_summary,
        "requires_role": "analyst",
        "schema": {
            "name": "get_sales_summary",
            "description": "Calculate completed orders, revenue, AOV, and refunds for an explicit date range (YYYY-MM-DD).",
            "parameters": {
                "type": "object",
                "properties": {
                    "start_date": {"type": "string", "description": "YYYY-MM-DD, inclusive."},
                    "end_date": {"type": "string", "description": "YYYY-MM-DD, inclusive."},
                },
                "required": ["start_date", "end_date"],
            },
        },
    },
    "compare_sales_periods": {
        "function": sales.compare_sales_periods,
        "requires_role": "analyst",
        "schema": {
            "name": "compare_sales_periods",
            "description": "Compare sales metrics between two explicit date ranges (e.g. this week vs last week).",
            "parameters": {
                "type": "object",
                "properties": {
                    "current_start": {"type": "string"}, "current_end": {"type": "string"},
                    "previous_start": {"type": "string"}, "previous_end": {"type": "string"},
                },
                "required": ["current_start", "current_end", "previous_start", "previous_end"],
            },
        },
    },
    "get_product_performance": {
        "function": sales.get_product_performance,
        "requires_role": "analyst",
        "schema": {
            "name": "get_product_performance",
            "description": "Rank products by revenue, units sold, or margin over a date range.",
            "parameters": {
                "type": "object",
                "properties": {
                    "start_date": {"type": "string"}, "end_date": {"type": "string"},
                    "sort_by": {"type": "string", "enum": ["revenue", "units", "margin"]},
                    "limit": {"type": "integer"},
                },
                "required": ["start_date", "end_date"],
            },
        },
    },
    "get_refund_summary": {
        "function": sales.get_refund_summary,
        "requires_role": "analyst",
        "schema": {
            "name": "get_refund_summary",
            "description": "Summarize refunds over a date range, optionally filtered by product category or refund reason.",
            "parameters": {
                "type": "object",
                "properties": {
                    "start_date": {"type": "string"}, "end_date": {"type": "string"},
                    "category": {"type": "string"}, "reason": {"type": "string"},
                },
                "required": ["start_date", "end_date"],
            },
        },
    },
    "get_stockout_risk": {
        "function": inventory.get_stockout_risk,
        "requires_role": "analyst",
        "schema": {
            "name": "get_stockout_risk",
            "description": "Estimate which variants may run out of stock soon, using recent sales velocity over a lookback window.",
            "parameters": {
                "type": "object",
                "properties": {
                    "lookback_days": {"type": "integer", "description": "Default 14."},
                    "limit": {"type": "integer"},
                },
                "required": [],
            },
        },
    },
    "calculate_reorder_quantity": {
        "function": inventory.calculate_reorder_quantity,
        "requires_role": "analyst",
        "schema": {
            "name": "calculate_reorder_quantity",
            "description": "Estimate how many units to reorder for one variant, given a target coverage window in days.",
            "parameters": {
                "type": "object",
                "properties": {
                    "variant_id": {"type": "string"},
                    "target_coverage_days": {"type": "integer", "description": "Default 14."},
                    "lookback_days": {"type": "integer", "description": "Default 30."},
                },
                "required": ["variant_id"],
            },
        },
    },
    "get_exchange_rate": {
        "function": external.get_exchange_rate,
        "requires_role": "analyst",
        "schema": {
            "name": "get_exchange_rate",
            "description": "Fetch a reference exchange rate between two currencies, for display only. Never used to convert stored figures.",
            "parameters": {
                "type": "object",
                "properties": {
                    "base_currency": {"type": "string", "description": "e.g. 'GBP'"},
                    "target_currency": {"type": "string", "description": "e.g. 'USD'"},
                },
                "required": ["base_currency", "target_currency"],
            },
        },
    },
    "propose_discount": {
        "function": approvals.propose_discount,
        "requires_role": "manager",
        "schema": {
            "name": "propose_discount",
            "description": "Prepare a discount proposal (products, percentage, date range) for human approval. Does NOT make the discount live.",
            "parameters": {
                "type": "object",
                "properties": {
                    "product_ids": {"type": "array", "items": {"type": "string"}},
                    "percentage": {"type": "number", "description": "0-90."},
                    "start_date": {"type": "string"}, "end_date": {"type": "string"},
                    "requester": {"type": "string", "description": "Identifier of who/what is requesting this."},
                },
                "required": ["product_ids", "percentage", "start_date", "end_date", "requester"],
            },
        },
    },
    "propose_inventory_alert": {
        "function": approvals.propose_inventory_alert,
        "requires_role": "manager",
        "schema": {
            "name": "propose_inventory_alert",
            "description": "Prepare a proposed change to a variant's reorder-alert threshold for human approval.",
            "parameters": {
                "type": "object",
                "properties": {
                    "variant_id": {"type": "string"},
                    "threshold": {"type": "integer"},
                    "requester": {"type": "string"},
                },
                "required": ["variant_id", "threshold", "requester"],
            },
        },
    },
}

ROLE_RANK = {"analyst": 0, "support": 1, "manager": 2}


def role_allows(role: str, requires_role: str) -> bool:
    """A higher-ranked role can do everything a lower-ranked role can.
    manager > support > analyst. This is intentionally a simple total
    order, not a real permissions matrix -- good enough to demonstrate
    the access-control requirement without over-building it."""
    return ROLE_RANK.get(role, -1) >= ROLE_RANK.get(requires_role, 99)


def gemini_tool_declarations() -> list[dict]:
    """The list of function schemas to hand to Gemini's `tools` parameter."""
    return [entry["schema"] for entry in TOOL_REGISTRY.values()]
