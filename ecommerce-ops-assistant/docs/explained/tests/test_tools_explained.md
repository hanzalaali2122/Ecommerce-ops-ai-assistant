# `tests/test_tools.py` — explained

**What it is:** the brief's milestone 2 — "six read-only tools tested
without Gemini" (this project has eleven read tools plus the approval
flow, all covered here). These tests call the Python functions in
`tools/*.py` directly: no model, no HTTP server. They prove the tools
work correctly on their own, before any AI reasoning is ever layered on
top of them.

## Two kinds of test in this file

**Most tests are self-contained.** Helpers like `_any_order_id()`,
`_any_customer_id()`, `_any_product_id()`, `_any_variant_id()` look up a
*real* ID from whatever database happens to be built, rather than
hard-coding one. These tests keep passing no matter which data source is
loaded (real UCI data, the stand-in generator, or a future replacement) —
they check shape and behavior ("does a not-found ID return an `error`
key instead of crashing", "does an analyst's view of an order redact the
customer ID"), not specific numbers.

**A handful of tests are ground-truth checks**, deliberately pinned to
specific dates, category names, or a specific product. These exist
because the brief asks the test suite to verify the assistant "finds the
intended evidence rather than inventing explanations" — which requires
*something* with a known right answer to check against. Since this
project uses real UCI data rather than fully synthetic data, that known
right answer comes from patterns *discovered* in the real data (recorded
with their exact source queries in `docs/data_profile.md`), not patterns
injected by a generator:

- `test_compare_sales_periods_no_saturday_trading` — this retailer has
  zero orders on any Saturday, anywhere in the dataset.
- `test_get_refund_summary_shows_known_high_refund_category` —
  `General Merchandise` has a materially higher refund *rate* than every
  other category.
- `test_loyal_customers_have_higher_aov_than_one_time_customers` —
  customers with 5+ orders have a real (if modest) AOV premium.
- `test_known_sales_gap_shows_zero_units_in_window` — one specific
  product (`ALARM CLOCK BAKELIKE GREEN`) had a real, 33-day gap in its
  sales history, used as a stand-in for a "did sales fall after a
  stockout"-shaped question — explicitly *not* claimed to be a proven
  stockout (the data doesn't support that claim; see
  `docs/data_profile.md` #4 for why).

If you swap the data source, these specific tests need new ground truth
from `docs/data_profile.md`'s method applied to the new data — not just
new numbers dropped into the same assertions.

## Coverage by file

| Tool file | Tests |
|---|---|
| `catalog.py` | search, not-found, found-with-variants, inventory shape |
| `orders.py` | not-found, found-with-items, analyst redaction, customer summary |
| `sales.py` | zero-sales safety, bad date-range rejection, the Saturday/refund-category/loyalty ground-truth checks, sort validation |
| `inventory.py` | stockout-risk shape, zero-sales reorder handling, the sales-gap ground-truth check |
| `external.py` | currency identity, unsupported-currency rejection |
| `approvals.py` | pending-only creation, pre-approval execution blocked, idempotent execution, >90% discount blocked |

## How to run these

```bash
python3 database/build_database.py   # build shop.db first, if you haven't
pytest tests/test_tools.py -v        # once pytest is installed
python3 tests/run_tests.py           # zero-dependency fallback
```
