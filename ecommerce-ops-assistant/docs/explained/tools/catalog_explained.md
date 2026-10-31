# `tools/catalog.py` — explained

**What it is:** the three simplest read-only tools in the project —
product search, product detail, and inventory lookup. Nothing here
calculates anything; it's all "look this ID up and hand back what's
there."

## The three functions

- **`search_products(query, category=None, limit=None)`** — a text
  search over product titles (`LIKE '%query%'`), optionally narrowed to
  one category, returning *product*-level summaries (not individual
  variants) with each product's price range and variant count. The idea
  is the model first finds the right `product_id` here, then calls
  `get_product_details` for the full picture — a deliberate two-step
  pattern so a vague search ("clock") doesn't dump every variant of every
  matching product into one response.
- **`get_product_details(product_id)`** — full detail for one product:
  its metadata plus every one of its variants. Returns
  `{"error": "not_found", ...}` for an unknown ID rather than raising an
  exception or, worse, inventing a plausible-looking fake record.
- **`get_inventory(variant_id)`** — current stock and reorder threshold
  for one variant, plus a `below_threshold` boolean the caller doesn't
  have to compute itself. Always includes a `note` reminding whoever
  reads it that this stock number is synthesized, not a live warehouse
  feed (UCI's real data has no stock-on-hand field at all).

## The pattern every function here follows

1. Validate arguments (`tools/validation.py`) — never trust the model's
   input blindly.
2. Run exactly one parameterized SQL query — `?` placeholders, never
   string-concatenated SQL, so there's no SQL-injection surface even
   though the "attacker" here is more likely to be a confused model than
   a malicious one.
3. Return a small plain dict — never thousands of raw rows — so the
   caller gets something it can reason about directly.

## How this connects to the rest of the project

`tools/schemas.py` registers all three functions in `TOOL_REGISTRY` so
the AI model (via `app/agent.py`) can call them, each requiring only the
`analyst` role (the lowest tier) — there's no sensitive data here worth
restricting further.
