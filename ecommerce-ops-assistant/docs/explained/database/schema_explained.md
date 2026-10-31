# `database/schema.sql` — explained

**What it is:** the blueprint for the SQLite database. Every table the
rest of the project reads or writes is declared here, with comments
explaining why each one exists.

## The tables, in plain language

Picture a real online shop's filing cabinet:

- **`customers`** — one row per person who ever bought something.
- **`products`** and **`variants`** — kept as *two* tables, not one, even
  though in this dataset each product only has one variant. Think of
  `products` as "WHITE HANGING HEART T-LIGHT HOLDER" and `variants` as
  "that item, specifically the one SKU we sell it as, at £2.55." A real
  store would have one product with many variants (sizes, colors); this
  dataset doesn't carry that detail, but the two-table shape is kept so
  the rest of the code — and any richer dataset you plug in later — works
  unchanged.
- **`orders`** and **`order_items`** — one row per order, one row per line
  within that order ("2 of the heart holder, 1 of the lantern").
- **`refunds`** — a cancelled line of an order. UCI marks a cancellation
  by prefixing the invoice number with `C` and making the quantity
  negative; the loader (`build_database.py`) detects that and writes a
  proper `refunds` row instead of mixing cancellations into normal sales.
- **`inventory`** and **`inventory_movements`** — how much stock is left,
  and a log of stock changing. UCI has *no* stock data at all (it's a
  record of past sales, not a live warehouse feed), so these are entirely
  invented — clearly marked as synthetic in the comments, and in every
  tool that reads them.
- **`discount_codes`** — promo codes. Also invented; UCI has no promo
  data.
- **`approval_requests`** — the human-approval inbox. Starts empty. A
  discount or inventory-alert proposal from the assistant lands here as
  `pending`; only a human (never the AI) can flip it to `approved` or
  `rejected`.
- **`tool_runs`** — the audit log. Every tool call the assistant makes —
  successful, blocked, or errored — gets one row here. This is what lets
  someone look at an answer and ask "prove it": find the `result_id` the
  answer cites, look it up in `tool_runs`, see exactly what was queried
  and what came back.

## Why keep `products` and `variants` separate if this data doesn't need it?

Because the brief's tool catalog (and every tool function downstream)
expects `variant_id` to exist — `get_inventory(variant_id)`,
`calculate_reorder_quantity(variant_id, ...)`, etc. If you ever plug in a
dataset that *does* have real variants (sizes, colors), nothing else in
the project has to change — only the loader that fills these tables.

## Why foreign keys and indexes

`PRAGMA foreign_keys = ON` at the top means SQLite will refuse to, say,
insert an `order_items` row pointing at a `variant_id` that doesn't
exist — a bug gets caught immediately instead of silently corrupting
data. The `CREATE INDEX` statements on `order_date`, `customer_id`,
`order_id`, `variant_id`, and `refund_date` exist because almost every
tool query filters or joins on one of those columns; without them, a
query over 500,000+ order_items rows would be slow.

## How this connects to the rest of the project

`database/build_database.py` is the only file that writes to this schema
directly (everything else goes through `tools/db.py`'s `get_connection()`
and the individual tool functions in `tools/*.py`, which only ever read,
except `tools/approvals.py` which writes `approval_requests` and
`tool_runs`).
