"""
generate_stand_in_data.py
--------------------------------------------------------------------------
WHAT THIS FILE IS FOR
This is NOT the real UCI "Online Retail" dataset. It is a stand-in with the
exact same column names the real dataset uses:

    InvoiceNo, StockCode, Description, Quantity, InvoiceDate, UnitPrice,
    CustomerID, Country

The real dataset lives at:
    https://archive.ics.uci.edu/dataset/352/online-retail
This sandbox has no internet access, so it could not be downloaded
automatically. Rather than block the whole project on that, this script
fabricates a same-shaped CSV so every downstream file (the loader, the
tools, the API, the frontend) can be built and tested end to end right now.

HOW TO SWITCH TO THE REAL DATA
Download "Online Retail.xlsx" from the link above, convert/save it as
data/online_retail_raw.csv with the same column names, and re-run
database/build_database.py. Nothing else needs to change -- the loader
only cares about those eight column names, not where the file came from.

WHY IT'S NOT JUST RANDOM NOISE
The project brief asks for synthetic data with "known patterns" baked in,
so the finished assistant's answers can be checked against ground truth
instead of just "looking plausible". This generator injects exactly the
six patterns the brief lists:

  1. Weekend sales increases       -> Saturday/Sunday order volume boosted
  2. A promo that raises order count but cuts margin
                                    -> a 25%-off code active for one week on
                                       a specific category
  3. A product whose sales fall after a stockout
                                    -> "Vintage Clock" sells steadily, then
                                       goes silent for 10 days starting
                                       2026-09-15 (simulated stockout)
  4. A category with unusually high refund rate
                                    -> "Fragile Glassware" gets ~18% of its
                                       invoices cancelled vs ~2% baseline
  5. Returning customers with higher AOV
                                    -> customers with 5+ orders get a markup
                                       on later orders
  6. Recent incomplete/cancelled orders
                                    -> a block of cancellations in the final
                                       week of data

A fixed random seed (42) makes this reproducible -- running the script
twice produces byte-identical output.
"""

import csv
import random
from datetime import datetime, timedelta

SEED = 42
random.seed(SEED)

OUTPUT_PATH = "data/online_retail_raw.csv"

# 12 months of data ending "today" in the fictional store's timeline.
# We pin this to a fixed date (not datetime.now()) so the injected patterns
# always land on the same real dates, and so running this script later
# doesn't silently shift "last week" out from under the rest of the system.
END_DATE = datetime(2026, 10, 18)   # a Sunday
START_DATE = END_DATE - timedelta(days=365)

COUNTRIES = ["United Kingdom"] * 70 + ["Germany", "France", "EIRE", "Spain",
                                        "Netherlands", "Belgium", "Portugal",
                                        "Australia", "Switzerland", "Norway"] * 3

# A small, fixed product catalog. Real UCI data has ~4000 distinct
# StockCodes; we use a much smaller set so the stand-in file stays small
# and the injected scenarios are easy to verify by eye.
CATEGORY_PRODUCTS = {
    "Home Decor": [
        ("85123A", "WHITE HANGING HEART T-LIGHT HOLDER", 2.55),
        ("84879", "ASSORTED COLOUR BIRD ORNAMENT", 1.69),
        ("22423", "REGENCY CAKESTAND 3 TIER", 12.75),
        ("21212", "PACK OF 72 RETROSPOT CAKE CASES", 0.55),
    ],
    "Vintage Clock": [
        ("22633", "VINTAGE UNION JACK CLOCK", 8.50),
        ("22634", "VINTAGE PARIS STATION CLOCK", 9.25),
    ],
    "Fragile Glassware": [
        ("22867", "HAND WARMER SCOTTY DOG DESIGN", 2.10),
        ("22866", "HAND WARMER SCOTTY DOG VINTAGE GLASS", 4.95),
        ("22865", "VINTAGE GLASS T-LIGHT HOLDER SET", 6.75),
    ],
    "Stationery": [
        ("21977", "PACK OF 60 PINK PAISLEY CAKE CASES", 0.55),
        ("21975", "PACK OF 60 DINOSAUR CAKE CASES", 0.55),
        ("17003", "BROCADE RING PURSE", 1.25),
    ],
    "Bags": [
        ("20725", "LUNCH BAG RED RETROSPOT", 1.65),
        ("20727", "LUNCH BAG BLACK SKULL", 1.65),
        ("20728", "LUNCH BAG SUKI DESIGN", 1.65),
    ],
    "Jewellery": [
        ("90210A", "ANTIQUE SILVER TEA SET", 15.00),
        ("90210B", "BRACELET VINTAGE LEAF DESIGN", 3.95),
    ],
    "Toys": [
        ("21481", "FAWN BLUE HOT WATER BOTTLE", 3.75),
        ("21482", "SPACEBOY LUNCH BOX", 1.95),
    ],
}

ALL_PRODUCTS = [
    (code, desc, price, cat)
    for cat, items in CATEGORY_PRODUCTS.items()
    for code, desc, price in items
]

N_CUSTOMERS = 400
CUSTOMER_IDS = [str(12000 + i) for i in range(N_CUSTOMERS)]
# A subset of "loyal" customers used for the returning-customer-AOV pattern.
LOYAL_CUSTOMERS = set(CUSTOMER_IDS[:60])
# ~8% of invoices have no customer id at all (guest checkout), same as UCI.
GUEST_RATE = 0.08

# The promo window: 25% off "Fragile Glassware" for one week.
PROMO_CODE = "GLASS25"
PROMO_CATEGORY = "Fragile Glassware"
PROMO_START = datetime(2026, 9, 1)
PROMO_END = datetime(2026, 9, 8)

# The stockout window for Vintage Clock products.
STOCKOUT_START = datetime(2026, 9, 15)
STOCKOUT_END = datetime(2026, 9, 25)

# The cancellation-heavy tail end of the dataset (recent incomplete orders).
CANCEL_SPIKE_START = END_DATE - timedelta(days=5)


def daterange(start, end):
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


def pick_customer():
    if random.random() < GUEST_RATE:
        return ""
    return random.choice(CUSTOMER_IDS)


def orders_for_day(day, invoice_counter):
    """Yield (invoice_no, rows) for every order placed on `day`."""
    is_weekend = day.weekday() >= 5  # Saturday=5, Sunday=6
    is_promo_week = PROMO_START <= day <= PROMO_END
    is_cancel_spike = day >= CANCEL_SPIKE_START

    # --- Pattern 1: weekend sales increase -----------------------------
    base_orders = random.randint(8, 14)
    if is_weekend:
        base_orders = int(base_orders * 1.6)
    # --- Pattern 2: promo raises order count -----------------------
    if is_promo_week:
        base_orders = int(base_orders * 1.3)

    day_orders = []
    for _ in range(base_orders):
        invoice_counter += 1
        invoice_no = str(536365 + invoice_counter)
        customer_id = pick_customer()
        is_loyal = customer_id in LOYAL_CUSTOMERS

        n_lines = random.randint(1, 5)
        lines = []
        for _ in range(n_lines):
            code, desc, price, category = random.choice(ALL_PRODUCTS)

            # --- Pattern 3: stockout silences Vintage Clock sales -------
            if category == "Vintage Clock" and STOCKOUT_START <= day <= STOCKOUT_END:
                continue

            qty = random.randint(1, 8)
            unit_price = price

            # --- Pattern 2 cont'd: promo discount cuts effective price --
            if is_promo_week and category == PROMO_CATEGORY:
                unit_price = round(price * 0.75, 2)

            # --- Pattern 5: loyal, returning customers spend more -------
            if is_loyal:
                qty = int(qty * 1.4) + 1

            lines.append((code, desc, qty, unit_price))

        if not lines:
            continue  # the whole order was for out-of-stock Vintage Clocks

        day_orders.append((invoice_no, day, customer_id, lines, False))

        # --- Pattern 4: Fragile Glassware gets cancelled far more often -
        has_glassware = any(
            desc for code, desc, qty, price in lines
            if code in {c for c, d, p in CATEGORY_PRODUCTS["Fragile Glassware"]}
        )
        cancel_chance = 0.02
        if has_glassware:
            cancel_chance = 0.18
        if is_cancel_spike:
            cancel_chance = max(cancel_chance, 0.30)

        if random.random() < cancel_chance:
            invoice_counter += 1
            cancel_invoice_no = "C" + str(536365 + invoice_counter)
            # Cancellation lines mirror the original order with negative qty,
            # exactly like real UCI cancellation invoices.
            cancel_lines = [(code, desc, -qty, price) for code, desc, qty, price in lines]
            day_orders.append((cancel_invoice_no, day, customer_id, cancel_lines, True))

    return day_orders, invoice_counter


def main():
    rows = []
    invoice_counter = 0
    for day in daterange(START_DATE, END_DATE):
        day_orders, invoice_counter = orders_for_day(day, invoice_counter)
        for invoice_no, day, customer_id, lines, is_cancel in day_orders:
            # Spread invoice timestamps realistically across business hours.
            ts = day + timedelta(hours=random.randint(8, 20), minutes=random.randint(0, 59))
            country = random.choice(COUNTRIES)
            for code, desc, qty, price in lines:
                rows.append({
                    "InvoiceNo": invoice_no,
                    "StockCode": code,
                    "Description": desc,
                    "Quantity": qty,
                    "InvoiceDate": ts.strftime("%Y-%m-%d %H:%M:%S"),
                    "UnitPrice": price,
                    "CustomerID": customer_id,
                    "Country": country,
                })

    with open(OUTPUT_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "InvoiceNo", "StockCode", "Description", "Quantity",
            "InvoiceDate", "UnitPrice", "CustomerID", "Country",
        ])
        writer.writeheader()
        writer.writerows(rows)

    print(f"Wrote {len(rows)} rows to {OUTPUT_PATH}")
    print(f"Date range: {START_DATE.date()} to {END_DATE.date()}")
    print("Injected scenarios (for later verification):")
    print(f"  - Weekend boost: every Saturday/Sunday")
    print(f"  - Promo {PROMO_CODE}: {PROMO_CATEGORY} at 25% off, "
          f"{PROMO_START.date()} to {PROMO_END.date()}")
    print(f"  - Stockout: Vintage Clock products, "
          f"{STOCKOUT_START.date()} to {STOCKOUT_END.date()}")
    print(f"  - High refund category: Fragile Glassware (~18% cancel rate)")
    print(f"  - Loyal customers (higher AOV): {len(LOYAL_CUSTOMERS)} ids, "
          f"first is {sorted(LOYAL_CUSTOMERS)[0]}")
    print(f"  - Cancellation spike: last 5 days of data "
          f"({CANCEL_SPIKE_START.date()} to {END_DATE.date()})")


if __name__ == "__main__":
    main()
