# `database/build_database.py` — explained

**What it is:** the bridge between a raw transactions CSV and a queryable
SQLite database. This is the file you run whenever the source data
changes.

## The big picture

```
data/online_retail_raw.csv  --[this file]-->  database/shop.db
```

It reads one flat CSV (one row per invoice line — the real UCI columns:
`InvoiceNo, StockCode, Description, Quantity, InvoiceDate, UnitPrice,
CustomerID, Country`) and sorts every row into the right normalized table
(`customers`, `products`, `variants`, `orders`, `order_items`, `refunds`),
then invents the handful of things the real data genuinely doesn't
contain (`inventory`, `inventory_movements`, `discount_codes`).

## Walking through `build()`, step by step

1. **Delete and recreate `shop.db`** from `schema.sql`. Safe to re-run any
   time — the database is fully rebuilt from the CSV, never patched.
2. **Read every usable row** from the CSV (`load_raw_rows`). A row is
   skipped (not crashed on) if its quantity or price can't be parsed, or
   if the price is negative — a handful of UCI rows are bookkeeping
   adjustments, not real sales lines.
3. **Pass 1 — discover.** Walk every row once to build three in-memory
   dictionaries: every distinct product (keeping its most recent
   description and price), every distinct customer (keeping their first
   country and first-seen date), and every invoice's lines grouped
   together.
4. **Write `customers`.** One row per distinct `CustomerID`. UCI has no
   names, so a placeholder name/email is generated — clearly fake
   (`customer17850@example-shop.test`), never passed off as real PII.
5. **Write `products` and `variants`.** `derive_category()` guesses a
   category from the product's description using a keyword list (see
   below) since UCI has no category column. `cost` is synthesized as
   `price / a random markup between 1.6x and 2.8x` — a plausible
   37%–64% gross margin for small retail goods, but explicitly a model,
   not real supplier cost data.
6. **Pass 2 — split invoices into orders vs. refunds.** An invoice number
   starting with `C` is UCI's own convention for a cancellation. Those
   become `refunds` rows; everything else becomes an `orders` +
   `order_items` pair. The code tries to match a cancellation back to the
   customer's most recent real order (a best-effort heuristic, not
   guaranteed correct — real refund matching would need a shared order
   reference, which UCI doesn't provide).
7. **Synthesize `inventory`.** For each variant, look at the last 30 days
   of real sales to estimate daily velocity, then invent a stock level
   between 5 and 40 days of coverage. A product with zero recent sales
   gets a small random baseline instead of 0, so "no sales" and "no
   stock" stay distinguishable when a tool reads this table.
8. **Synthesize `discount_codes`.** A few generic promo codes so
   `propose_discount`-adjacent code has real rows to read. Not tied to
   any actual sales pattern (see `docs/data_profile.md` §5 for why).

## `derive_category()` — the category heuristic

UCI's real "Online Retail" dataset has ~4,070 distinct products and no
category field. `derive_category()` checks a product's description
against an ordered list of keyword groups (`CATEGORY_KEYWORDS`) and
returns the first match, falling back to `"General Merchandise"`. This
list was tuned by frequency-counting the most common words across every
real product description (see `docs/data_profile.md`) — it classifies
about two-thirds of real products into a meaningful category. It's a
heuristic, not a real taxonomy, and the code says so.

## Why real UCI data instead of the fabricated stand-in?

An earlier version of this project (still present as
`database/generate_stand_in_data.py`) fabricated a small CSV with the
same column shape, because the sandbox it was first built in had no
internet access. This version uses the actual UCI dataset — see
`data/convert_real_dataset.py` for how it was obtained — so every number
the tools report reflects a real retailer's real transaction history,
not an invented one.

## Run it with

```bash
python3 database/build_database.py
```
from the project root.
