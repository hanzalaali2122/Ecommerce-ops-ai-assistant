"""
build_database.py
--------------------------------------------------------------------------
WHAT THIS FILE DOES, IN PLAIN LANGUAGE

This is the bridge between "a CSV of raw transactions" and "a database the
rest of the app can query with simple, narrow SQL". It:

  1. Reads data/online_retail_raw.csv (the UCI-style columns: InvoiceNo,
     StockCode, Description, Quantity, InvoiceDate, UnitPrice, CustomerID,
     Country).
  2. Creates database/shop.db from database/schema.sql.
  3. Walks through every row and sorts it into the right tables:
       - a row with a normal InvoiceNo (not starting with "C") becomes part
         of an `orders` + `order_items` record.
       - a row with InvoiceNo starting "C" (UCI's own convention for a
         cancellation) becomes a `refunds` record instead, and is matched
         back to its original order when one can be found.
       - every distinct StockCode becomes one `products` row and one
         `variants` row (UCI doesn't have real size/color variants, so each
         product gets exactly one variant -- see schema.sql for why that's
         still useful).
       - every distinct CustomerID becomes one `customers` row.
  4. Synthesizes the things UCI genuinely does not contain, clearly marked
     as synthetic at each step: cost (hence margin), current inventory
     levels and reorder thresholds, inventory movement history, and a
     couple of discount codes. A fixed random seed keeps this reproducible.

WHY TRANSFORM AT ALL INSTEAD OF QUERYING THE CSV DIRECTLY?
Two reasons. First, the brief's tool catalog assumes a normalized,
indexed, relational schema (get_order, get_customer_summary, etc. all
assume foreign keys exist). Second, real transactional data is messy --
UCI's Description field has inconsistent casing/whitespace, some rows have
negative quantities that aren't cancellations (returns/adjustments), and
some rows have no CustomerID at all. Cleaning that up once, here, means
every tool downstream can trust the data it reads instead of re-deriving
these rules on every query.

WHERE data/online_retail_raw.csv COMES FROM
As of this build, data/online_retail_raw.csv IS the real UCI "Online
Retail" dataset (541,909 raw rows, Dec 2010 - Dec 2011, a UK-based online
gift retailer) -- not the stand-in generator's fabricated data. The
original archive.ics.uci.edu download page was not reachable from this
project's network (egress is allowlisted to package registries and
GitHub only), so the real "Online Retail.xlsx" file was obtained via
`git clone` of a public GitHub mirror of the dataset
(github.com/eaintkyawthmu/UCI_Online_Retail_Dataset_Cleaned_Version) and
converted to this CSV with data/convert_real_dataset.py. See
docs/data_profile.md for the full provenance note and for the real,
*discovered* business patterns in this data (as opposed to the stand-in
generator's *injected* ones) that tests/test_tools.py checks against.

database/generate_stand_in_data.py still exists and still works -- it's a
useful fallback if you ever want fully controllable synthetic data again
(e.g. to test against patterns with a perfectly known ground truth), but
it is no longer what this file reads by default.

RUN THIS WITH:
    python3 database/build_database.py
It is safe to re-run: it deletes any existing shop.db and rebuilds from
scratch, so the resulting database always matches whatever is currently in
data/online_retail_raw.csv.
"""

import csv
import os
import random
import sqlite3
import sys
import uuid
from collections import defaultdict
from datetime import datetime, timedelta

SEED = 42
random.seed(SEED)

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
RAW_CSV_PATH = os.path.join(ROOT, "data", "online_retail_raw.csv")
SCHEMA_PATH = os.path.join(HERE, "schema.sql")
DB_PATH = os.path.join(HERE, "shop.db")

# Category keyword map, used only to derive a `products.category` value
# from free-text descriptions since UCI has no category column. This is a
# heuristic, not ground truth -- good enough for "category with a high
# refund rate" style questions, not a real taxonomy.
#
# Tuned against the REAL UCI "Online Retail" dataset's ~4,070 distinct
# product descriptions (see docs/data_profile.md for how this was
# measured): the original seven-category list, written against the small
# stand-in catalog, only classified ~23% of real products and dumped the
# rest into "General Merchandise". This expanded list was built by
# frequency-counting the most common words across real descriptions and
# grouping them into categories a shop floor would recognize, in order
# from most specific match to most generic (first match wins, so "glass
# candle holder" lands in Glassware, not Candles & Lighting, because
# Glassware is checked first).
CATEGORY_KEYWORDS = [
    ("Seasonal & Christmas", ["christmas", "xmas", "easter", "halloween", "valentine", "advent"]),
    ("Vintage Clock", ["clock"]),
    ("Glassware", ["glass", "hand warmer"]),
    ("Candles & Lighting", ["candle", "t-light", "tealight", "lantern", "light"]),
    ("Jewellery & Accessories", ["necklace", "bracelet", "earring", "charm", "brooch", "ring"]),
    ("Bags & Purses", ["bag", "purse", "wallet"]),
    ("Kitchen & Dining", ["mug", "cup", "bowl", "plate", "kitchen", "cake", "teapot",
                           "tea set", "bottle", "jam", "spoon", "fork", "knife"]),
    ("Garden & Outdoor", ["garden", "plant", "birdhouse", "watering"]),
    ("Stationery & Cards", ["card", "paper", "notebook", "pencil", "stamp", "wrap", "envelope"]),
    ("Toys & Games", ["toy", "game", "doll", "puzzle", "spaceboy", "lunch box"]),
    ("Storage & Containers", ["box", "tin", "basket", "jar"]),
    ("Home Decor", ["holder", "ornament", "cakestand", "frame", "mirror", "hook", "sign",
                     "wall", "cushion", "garland", "hanging", "decoration", "vase"]),
]


def derive_category(description: str) -> str:
    desc = description.lower()
    for category, keywords in CATEGORY_KEYWORDS:
        if any(k in desc for k in keywords):
            return category
    return "General Merchandise"


def parse_invoice_date(raw: str) -> datetime:
    # The stand-in generator writes "YYYY-MM-DD HH:MM:SS"; real UCI exports
    # are usually "MM/DD/YYYY HH:MM" -- we try both so a real file drops in
    # without edits.
    for fmt in ("%Y-%m-%d %H:%M:%S", "%m/%d/%Y %H:%M", "%d/%m/%Y %H:%M"):
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    raise ValueError(f"Unrecognized InvoiceDate format: {raw!r}")


def load_raw_rows(path):
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                qty = int(row["Quantity"])
                price = float(row["UnitPrice"])
            except (ValueError, KeyError):
                continue  # skip malformed rows rather than crash the whole load
            if price < 0:
                continue  # a handful of UCI rows are bookkeeping adjustments, not sales
            yield {
                "invoice_no": row["InvoiceNo"].strip(),
                "stock_code": row["StockCode"].strip(),
                "description": (row.get("Description") or "UNKNOWN ITEM").strip(),
                "quantity": qty,
                "invoice_date": parse_invoice_date(row["InvoiceDate"].strip()),
                "unit_price": price,
                "customer_id": (row.get("CustomerID") or "").strip(),
                "country": (row.get("Country") or "Unknown").strip(),
            }


def build():
    if not os.path.exists(RAW_CSV_PATH):
        sys.exit(
            f"Could not find {RAW_CSV_PATH}.\n"
            f"Run database/generate_stand_in_data.py first, or place a real "
            f"UCI-formatted CSV at that path."
        )

    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)

    conn = sqlite3.connect(DB_PATH)
    with open(SCHEMA_PATH) as f:
        conn.executescript(f.read())

    print("Reading raw rows...")
    rows = list(load_raw_rows(RAW_CSV_PATH))
    print(f"  {len(rows)} usable line rows")

    # ------------------------------------------------------------------
    # Pass 1: discover products, variants, customers from the raw rows.
    # ------------------------------------------------------------------
    products = {}       # stock_code -> {description, last_price}
    customers = {}       # customer_id -> {country, first_seen}
    invoices = defaultdict(list)  # invoice_no -> list of raw rows

    for r in rows:
        code = r["stock_code"]
        if code not in products or r["invoice_date"] >= products[code]["last_seen"]:
            products[code] = {
                "description": r["description"],
                "last_price": r["unit_price"],
                "last_seen": r["invoice_date"],
            }
        if r["customer_id"]:
            cust = customers.setdefault(r["customer_id"], {
                "country": r["country"], "first_seen": r["invoice_date"],
            })
            if r["invoice_date"] < cust["first_seen"]:
                cust["first_seen"] = r["invoice_date"]
                cust["country"] = r["country"]
        invoices[r["invoice_no"]].append(r)

    print(f"  {len(products)} distinct products")
    print(f"  {len(customers)} distinct customers")
    print(f"  {len(invoices)} distinct invoices")

    # ------------------------------------------------------------------
    # Write customers
    # ------------------------------------------------------------------
    customer_rows = []
    for i, (cid, info) in enumerate(sorted(customers.items())):
        customer_rows.append((
            cid,
            f"Customer {cid}",                     # UCI has no real names
            f"customer{cid}@example-shop.test",     # clearly-fake placeholder email
            info["country"],
            info["first_seen"].date().isoformat(),
        ))
    conn.executemany(
        "INSERT INTO customers (customer_id, name, email, country, created_date) "
        "VALUES (?, ?, ?, ?, ?)",
        customer_rows,
    )

    # ------------------------------------------------------------------
    # Write products + variants (one variant per product, see schema.sql)
    # cost is synthesized as price * a random markup factor between
    # 1.6x and 2.8x (i.e. a 37%-64% gross margin), which is a realistic
    # range for small retail goods. This is explicitly a model, not real
    # cost data -- UCI does not contain supplier costs.
    # ------------------------------------------------------------------
    thirty_days_before_end = max(r["invoice_date"] for r in rows) - timedelta(days=60)
    product_rows = []
    variant_rows = []
    for code, info in sorted(products.items()):
        category = derive_category(info["description"])
        status = "active" if info["last_seen"] >= thirty_days_before_end else "discontinued"
        markup = random.uniform(1.6, 2.8)
        cost = round(info["last_price"] / markup, 2) if info["last_price"] > 0 else 0.5
        product_rows.append((code, info["description"], category, status))
        variant_rows.append((
            f"{code}-V1", code, code, None, None,
            round(info["last_price"], 2), cost,
        ))
    conn.executemany(
        "INSERT INTO products (product_id, title, category, status) VALUES (?, ?, ?, ?)",
        product_rows,
    )
    conn.executemany(
        "INSERT INTO variants (variant_id, product_id, sku, size, color, price, cost) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        variant_rows,
    )
    cost_by_variant = {f"{code}-V1": cost for (code, info) in products.items()
                        for cost in [next(v[6] for v in variant_rows if v[0] == f"{code}-V1")]}

    # ------------------------------------------------------------------
    # Pass 2: split invoices into orders (+ order_items) vs refunds.
    # A cancellation invoice (InvoiceNo starting "C") is matched to its
    # most recent prior order from the same customer for the same
    # products, when one exists; otherwise it's recorded with order_id
    # left NULL (an unmatched refund, which is realistic -- real stores
    # get these too).
    # ------------------------------------------------------------------
    order_rows = []
    item_rows = []
    refund_rows = []

    # Index completed orders by customer for refund matching.
    customer_recent_orders = defaultdict(list)  # customer_id -> [order_id,...] in order

    sorted_invoices = sorted(invoices.items(), key=lambda kv: kv[1][0]["invoice_date"])

    for invoice_no, line_rows in sorted_invoices:
        is_cancellation = invoice_no.upper().startswith("C")
        invoice_date = min(r["invoice_date"] for r in line_rows)
        customer_id = next((r["customer_id"] for r in line_rows if r["customer_id"]), None)

        if not is_cancellation:
            subtotal = sum(r["quantity"] * r["unit_price"] for r in line_rows)
            order_rows.append((
                invoice_no, customer_id or None, invoice_date.isoformat(sep=" "),
                "completed", "GBP", round_money(subtotal), 0.0, round_money(subtotal),
            ))
            for r in line_rows:
                item_rows.append((
                    invoice_no, f"{r['stock_code']}-V1", r["quantity"], r["unit_price"], 0.0,
                ))
            if customer_id:
                customer_recent_orders[customer_id].append(invoice_no)
        else:
            refund_amount = sum(abs(r["quantity"]) * r["unit_price"] for r in line_rows)
            matched_order_id = None
            if customer_id and customer_recent_orders.get(customer_id):
                matched_order_id = customer_recent_orders[customer_id][-1]
            variant_id = f"{line_rows[0]['stock_code']}-V1"
            refund_rows.append((
                matched_order_id, variant_id, invoice_date.isoformat(sep=" "),
                round_money(refund_amount), "customer_cancellation",
            ))
            # A matched, cancelled order is also recorded as its own
            # 'cancelled' order row so order-level status queries (and
            # get_order) see consistent data, with zero net revenue impact
            # since get_sales_summary only counts 'completed' orders.
            if not matched_order_id:
                order_rows.append((
                    invoice_no, customer_id or None, invoice_date.isoformat(sep=" "),
                    "cancelled", "GBP", round_money(refund_amount), 0.0, round_money(refund_amount),
                ))
                # An unmatched cancellation still needs order_items so
                # get_order can show what was in it -- without this, these
                # orders would silently look empty to anyone inspecting them.
                for r in line_rows:
                    item_rows.append((
                        invoice_no, f"{r['stock_code']}-V1", abs(r["quantity"]), r["unit_price"], 0.0,
                    ))

    conn.executemany(
        "INSERT INTO orders (order_id, customer_id, order_date, status, currency, "
        "subtotal, discount_total, total) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        order_rows,
    )
    conn.executemany(
        "INSERT INTO order_items (order_id, variant_id, quantity, unit_price, discount) "
        "VALUES (?, ?, ?, ?, ?)",
        item_rows,
    )
    conn.executemany(
        "INSERT INTO refunds (order_id, variant_id, refund_date, amount, reason) "
        "VALUES (?, ?, ?, ?, ?)",
        refund_rows,
    )
    print(f"  wrote {len(order_rows)} orders, {len(item_rows)} order_items, "
          f"{len(refund_rows)} refunds")

    # ------------------------------------------------------------------
    # Synthesize inventory: for each variant, look at the last 30 days of
    # sales to estimate daily velocity, then set available stock to a
    # randomized 5-40 days of coverage. reorder_threshold is set to ~7
    # days of coverage. This is explicitly synthetic -- UCI has no stock
    # data at all.
    # ------------------------------------------------------------------
    max_date = max(r["invoice_date"] for r in rows)
    window_start = max_date - timedelta(days=30)
    recent_sales = defaultdict(int)
    for r in rows:
        if r["invoice_date"] >= window_start:
            recent_sales[f"{r['stock_code']}-V1"] += r["quantity"]

    inventory_rows = []
    movement_rows = []
    for v in variant_rows:
        variant_id = v[0]
        daily_velocity = recent_sales.get(variant_id, 0) / 30.0
        coverage_days = random.uniform(5, 40)
        available = max(0, round(daily_velocity * coverage_days))
        # Give zero-velocity products a small baseline stock instead of 0,
        # so "no sales" and "no stock" stay distinguishable in queries.
        if daily_velocity == 0:
            available = random.randint(0, 15)
        reorder_threshold = max(5, round(daily_velocity * 7))
        inventory_rows.append((variant_id, available, reorder_threshold))

        # A couple of synthetic movement log entries per variant.
        if available > 0:
            movement_rows.append((
                variant_id, available, "restock",
                (max_date - timedelta(days=random.randint(1, 20))).isoformat(sep=" "),
            ))
        sold = recent_sales.get(variant_id, 0)
        if sold > 0:
            movement_rows.append((
                variant_id, -sold, "sale", max_date.isoformat(sep=" "),
            ))

    conn.executemany(
        "INSERT INTO inventory (variant_id, available_units, reorder_threshold) VALUES (?, ?, ?)",
        inventory_rows,
    )
    conn.executemany(
        "INSERT INTO inventory_movements (variant_id, quantity_change, reason, occurred_at) "
        "VALUES (?, ?, ?, ?)",
        movement_rows,
    )
    print(f"  synthesized inventory for {len(inventory_rows)} variants")

    # ------------------------------------------------------------------
    # Synthesize a handful of discount codes so propose_discount /
    # history-lookup tools have real rows to find. UCI's real data has no
    # promo-code field at all, so these are entirely synthetic examples,
    # not tied to any pattern in the real sales data (see
    # docs/data_profile.md for why: with real historical data there is no
    # controlled "promo window" to inject -- the brief's promo-margin
    # scenario is demonstrated instead with propose_discount's own
    # before/after margin estimate, computed live from real sales velocity
    # and cost for whatever products are actually proposed).
    # ------------------------------------------------------------------
    discount_rows = [
        ("WELCOME10", 10.0, "2025-01-01", "2030-12-31"),
        ("SUMMER15", 15.0, "2026-06-01", "2026-06-30"),
        ("CLEARANCE20", 20.0, "2026-01-01", "2026-01-31"),
    ]
    conn.executemany(
        "INSERT INTO discount_codes (code, percentage, start_date, expiry_date) VALUES (?, ?, ?, ?)",
        discount_rows,
    )

    conn.commit()
    conn.close()
    print(f"Done. Database written to {DB_PATH}")


def round_money(v):
    return round(v + 1e-9, 2)


if __name__ == "__main__":
    build()
