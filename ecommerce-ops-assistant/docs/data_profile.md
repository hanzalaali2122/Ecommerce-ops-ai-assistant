# Data profile: ground truth for the real UCI dataset

The project brief (milestone 1) asks the
database generator to inject known business patterns — a weekend sales
boost, a margin-cutting promo, a stockout, a high-refund category, a
returning-customer AOV premium, a late cancellation spike — with a fixed
random seed, specifically so the finished assistant's answers can be
checked against a ground truth instead of just "looking plausible".

This project uses the **real UCI "Online Retail" dataset** instead of
fully synthetic data (541,909 transaction rows, Dec 2010–Dec 2011, a
UK-based online gift wholesaler — see `data/convert_real_dataset.py` for
how the file was obtained). Real historical data can't be *injected* with
a chosen pattern on a chosen date — but it already contains real
patterns. This document plays the same role the brief's "record the
injected scenarios" step would have: it writes down, with exact numbers,
what the real data actually shows, so `tests/test_tools.py` has something
concrete to check the tools against, and so a person reading an
investigation's output can sanity-check it against known facts rather
than trusting it blindly.

Every number below was computed directly from `database/shop.db` after a
fresh build (`python3 database/build_database.py`); the exact queries are
in the git history of this file / reproducible with the snippets shown.

## 1. Weekday pattern (not a weekend boost — the opposite)

```sql
SELECT strftime('%w', order_date) AS day_of_week, COUNT(*), SUM(total)
FROM orders WHERE status = 'completed' GROUP BY day_of_week;
```

| Day (SQLite %w) | Orders | Revenue (GBP) |
|---|---|---|
| 0 = Sunday    | 2,207 | 813,827.61 |
| 1 = Monday    | 3,420 | 1,779,575.04 |
| 2 = Tuesday   | 3,973 | 2,178,632.61 |
| 3 = Wednesday | 4,142 | 1,851,147.81 |
| 4 = Thursday  | 4,689 | 2,203,161.24 |
| 5 = Friday    | 3,631 | 1,840,340.23 |
| 6 = Saturday  | **0** | **0** |

**Finding:** this retailer does not trade on Saturdays at all — there is
not a single completed order with `strftime('%w', order_date) = '6'`
anywhere in the dataset. Sunday is the lowest-volume day that *does* have
orders. Thursday is the highest. This is the opposite of the brief's
assumed "weekend sales increase" pattern, which makes it a good
first-question evaluation case precisely because it would catch an
assistant that assumes a textbook retail pattern instead of checking the
real data (`get_sales_summary` on any Saturday date range should always
return `completed_orders: 0`).

## 2. Category with the highest refund rate

```sql
SELECT p.category, COUNT(DISTINCT r.refund_id) AS refunds,
       COUNT(DISTINCT oi.order_id) AS orders_in_category
FROM products p
JOIN variants v ON v.product_id = p.product_id
LEFT JOIN order_items oi ON oi.variant_id = v.variant_id
LEFT JOIN refunds r ON r.variant_id = v.variant_id
GROUP BY p.category;
```

| Category | Refunds | Orders | Refund rate |
|---|---|---|---|
| **General Merchandise** | 1,429 | 18,710 | **7.64%** |
| Kitchen & Dining | 659 | 13,077 | 5.04% |
| Vintage Clock | 96 | 2,783 | 3.45% |
| Glassware | 192 | 6,014 | 3.19% |
| Home Decor | 323 | 12,098 | 2.67% |
| Storage & Containers | 308 | 11,261 | 2.74% |
| Candles & Lighting | 255 | 9,733 | 2.62% |
| Bags & Purses | 228 | 9,342 | 2.44% |
| Seasonal & Christmas | 121 | 6,153 | 1.97% |
| Toys & Games | 73 | 5,930 | 1.23% |
| Garden & Outdoor | 44 | 3,714 | 1.18% |
| Jewellery & Accessories | 39 | 5,203 | 0.75% |
| Stationery & Cards | 69 | 9,229 | 0.75% |

**Finding:** `General Merchandise` — the catch-all bucket for products the
category heuristic in `database/build_database.py` couldn't classify more
specifically — has a noticeably higher refund rate (7.64%) than every
named category, roughly 1.5x the next-highest (Kitchen & Dining, 5.04%)
and over 10x the lowest (Jewellery & Accessories / Stationery & Cards,
0.75%). `get_refund_summary` over the full dataset window should surface
this. This is reported as an *association*, consistent with the brief's
instruction to distinguish association from causation — nothing here
proves a causal reason refund rates differ by category.

## 3. Returning-customer AOV premium (real, but modest)

```sql
SELECT customer_id, COUNT(*) AS n, AVG(total) AS aov
FROM orders WHERE status = 'completed' AND customer_id IS NOT NULL
GROUP BY customer_id;
```

| Customer group | Customers | Avg order value (GBP) |
|---|---|---|
| One-time (1 completed order) | 1,494 | 412.52 |
| Loyal (5+ completed orders) | 1,115 | 426.49 |

**Finding:** loyal customers do have a higher average order value, but
the effect in the real data (≈3.4%) is much smaller than a synthetic
generator would typically inject. This is an honest result worth keeping
rather than smoothing over: `tests/test_tools.py` checks the *direction*
(loyal ≥ one-time) rather than asserting a specific magnitude, and any
investigation answer citing this pattern should describe it as modest,
not dramatic.

## 4. A real, observed sales gap (stockout-shaped, not provably a stockout)

Found by scanning every variant with 30+ sales events for the single
longest gap between consecutive sale dates, excluding obviously seasonal
items (a Christmas decoration selling only in Nov/Dec is seasonality, not
a stockout — see note below) and requiring at least 10 sales both before
and after the gap, so the "before" and "after" trend is real.

**`ALARM CLOCK BAKELIKE GREEN` (variant `22726-V1`)** sold steadily
(328 sales events before), then had **zero sales from 2011-05-13 to
2011-06-16** (33 days), then resumed and sold even more afterward (672
sales events after). `get_product_performance("2011-05-14", "2011-06-15",
sort_by="units")` should show no `ALARM CLOCK BAKELIKE GREEN` line at all
for that window.

**Important limitation, stated plainly because the brief insists on it:**
the real data has no inventory-movement history from 2011, so there is no
way to *confirm* this gap was caused by a stockout rather than, say, a
temporary delisting or a data-collection gap. It is reported here exactly
as the brief's Workflow A asks — "a stockout may explain part of a
decline, but the data does not prove it caused every lost sale" — as an
*observed sales gap*, not a proven stockout.

**Seasonality caveat:** the single longest sales gaps in the whole
dataset actually belong to Christmas items (e.g. `GLITTER CHRISTMAS TREE
WITH BELLS`, idle from Sept 2011 to the following Dec), which is normal
seasonal demand, not a supply problem. This is itself a useful case:
anyone — human or assistant — reading "X stopped selling for 9 months"
needs to check whether the product is seasonal before concluding
anything is wrong.

## 5. Why discount_codes has no "known promo window" to check

UCI's real data has no promo-code or discount field at all, so unlike the
other four patterns above, there is no real discount event to discover.
`database/build_database.py` synthesizes a few generic `discount_codes`
rows so `propose_discount`-adjacent tools have real rows to read, but
none of them are tied to an actual change in real sales data. Workflow D
("prepare a discount, check margin impact") is instead verified the way
the brief's own evaluation table frames it — checking that
`propose_discount` computes a correct *before/after margin estimate* for
whatever products are actually proposed, using real recent sales velocity
and cost, not by rediscovering a pre-existing promo in the data.

## Reproducing this profile

```bash
python3 database/build_database.py   # rebuild shop.db from data/online_retail_raw.csv
sqlite3 database/shop.db < docs/profile_queries.sql   # see that file for the exact queries above
```
