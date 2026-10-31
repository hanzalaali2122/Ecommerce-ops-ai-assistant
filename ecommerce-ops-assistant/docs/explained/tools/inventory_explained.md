# `tools/inventory.py` — explained

**What it is:** Workflow B's two tools — "which products may run out
within two weeks, and how much should we reorder?"

## The formulas (copied verbatim from the brief, on purpose)

```
Average daily units      = units sold / days observed
Estimated days remaining = available stock / average daily units
Suggested reorder        = max(0, target coverage days × average daily
                                units − available stock)
```

Both divide by "average daily units," which is zero for any product with
no recent sales. Every division here goes through
`metrics.safe_divide`, which returns `0.0` instead of raising — this is
the brief's "zero sales → avoid division by zero" requirement, satisfied
structurally rather than with a scattered `if` check in each function.

## `get_stockout_risk(lookback_days=14, limit=50)`

For *every* variant, joins recent sales (within the lookback window) to
current stock and computes `estimated_days_remaining`. Products are
split into two buckets in the result:

- `at_risk_within_14_days` — has sales velocity, and will run out soon.
- `zero_sales_products` — no sales at all in the window, so "days
  remaining" genuinely can't be calculated (dividing by zero sales is
  meaningless, not just mathematically undefined) — the brief explicitly
  asks for these to be "handled separately," so they get their own
  bucket instead of being silently sorted to the bottom with a fake
  "infinite" value.

## `calculate_reorder_quantity(variant_id, target_coverage_days=14,
lookback_days=30)`

For one specific variant: looks up current stock and recent sales
velocity, then applies the reorder formula. If there's no sales in the
lookback window, it returns a `zero_sales: true` result with a `note`
saying this needs manual review — explicitly *not* a reorder number
invented from nothing.

Every successful (non-zero-sales) result also carries a `caveat`:
"this is a starting estimate... it does not account for seasonality,
supplier lead times, or demand earlier stockouts may have suppressed."
That's not boilerplate — it's the brief's own stated limitation, kept
attached to the number itself so whoever reads the tool's output (human
or model) sees the caveat in the same place as the number, not buried in
a separate document.

## Why this tool depends on `get_stockout_risk` or `get_inventory` running
first (in the Gemini loop)

`calculate_reorder_quantity` needs *both* current stock (from
`inventory`) and recent sales (from `order_items`) for the same variant.
In the brief's words: "a reorder calculation must wait for the inventory
and sales results it depends on" — this is a *dependent* call, not one
that can run in parallel with an initial stock check the way two
independent reads could.

## How this connects to the rest of the project

`app/mock_agent.py`'s Workflow B handler calls `get_stockout_risk` first,
then `calculate_reorder_quantity` for each at-risk variant it found — the
dependency ordering described above, made concrete.
