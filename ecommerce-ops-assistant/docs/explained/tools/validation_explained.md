# `tools/validation.py` — explained

**What it is:** every argument-checking rule in the project, in one
place, so two different tools can never quietly disagree about what a
valid date range or a valid discount percentage looks like.

## Why this matters for an AI-driven system specifically

Every function in `tools/*.py` can be called by an AI model that just
decided, on its own, what arguments to pass. The model might pass a
malformed date, a negative quantity, or ask for 50,000 rows back. This
file is the layer that says "no" to all of that — safely, with a message
clear enough for the model itself to read and correct its next attempt,
rather than crashing the whole request.

## The pieces

- **`ToolValidationError`** — a custom exception (subclassing
  `ValueError`) with one rule: its message is always safe to show
  directly to a person or an AI model. `app/agent.py` specifically
  catches this exception type and turns it into a structured `{"error":
  ..., "message": ...}` tool result instead of letting the whole request
  crash — this is what lets the model see "oh, that date was invalid"
  and try again with a fix, rather than the investigation just failing.
- **`require_non_empty_string`** — used for every ID argument
  (`product_id`, `order_id`, `customer_id`, ...). Rejects `None`, `""`,
  and whitespace-only strings.
- **`validate_date_string` / `validate_date_range`** — parses
  `"YYYY-MM-DD"` strictly, rejects an end date before a start date, and
  caps the span at `MAX_DATE_RANGE_DAYS` (366 — a little over a year,
  since the dataset itself only spans about a year). That cap exists
  specifically so a careless "show me everything" request can't trigger
  a query scanning the entire 500,000+-row `order_items` table.
- **`validate_positive_int` / `validate_limit`** — used for things like
  `lookback_days`, `target_coverage_days`, and result-set `limit`s.
  `validate_limit` additionally hard-caps at `MAX_RESULT_ROWS` (200) —
  this is the brief's "do not return thousands of raw orders for the
  model to add together" rule, enforced in code rather than hoped for.
- **`validate_currency`** — restricts to a small allowlist
  (`GBP, USD, EUR`), case-insensitive.
- **`validate_percentage`** — specifically for discount proposals:
  must be a number strictly between 0 and 90. The upper bound is a
  deliberate business rule ("discounts above 90% are blocked as almost
  certainly a mistake"), not just type-checking.

## Why centralize this instead of validating inline in each tool

Two tools that each hand-roll their own date validation will drift —
one might accept a 2-year range, another might reject it, and nobody
decided that difference on purpose. By routing every tool's validation
through this one file, a rule change (say, raising the date-range cap)
happens in exactly one place and applies everywhere at once.
