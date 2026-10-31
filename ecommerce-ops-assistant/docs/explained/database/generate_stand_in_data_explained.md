# `database/generate_stand_in_data.py` — explained

**What it is:** a *fallback* data generator, kept in the project but not
used by default. It fabricates a small CSV with the exact same column
shape as the real UCI dataset, with six specific business patterns
deliberately baked in at known dates.

## Why it still exists

This file was the project's original data source, written when the
sandbox it was built in had no internet access to download the real UCI
file. The current project uses real UCI data instead (see
`data/convert_real_dataset.py` and `docs/data_profile.md`), but this
generator is kept because it's genuinely useful for a different purpose:
**fully controllable test data.** Real historical data shows you whatever
patterns actually happened to occur; this generator lets you *choose*
exactly what pattern happens, on exactly what date, so you can write a
test with a perfectly known right answer.

## What it injects, and how

With a fixed random seed (42, for reproducibility — running it twice
produces byte-identical output), it generates 12 months of fake orders
with six patterns layered in:

1. **Weekend boost** — order volume on Saturdays/Sundays is multiplied by
   1.6x.
2. **A margin-cutting promo** — for one week (`PROMO_START`–`PROMO_END`),
   orders increase 1.3x but "Fragile Glassware" items sell at 25% off.
3. **A stockout** — "Vintage Clock" products are silently excluded from
   every order during a 10-day window, simulating being out of stock.
4. **A high-refund category** — "Fragile Glassware" orders get an 18%
   chance of being cancelled (vs. 2% baseline for everything else).
5. **Returning-customer AOV premium** — a fixed set of "loyal" customer
   IDs buy 40% more per line than everyone else.
6. **A late cancellation spike** — the final 5 days of the generated
   dataset have an elevated cancellation rate (≥30%), simulating a recent
   operational problem.

## How to switch back to it

```bash
python3 database/generate_stand_in_data.py   # writes data/online_retail_raw.csv
python3 database/build_database.py           # rebuilds shop.db from it
```

If you do this, the ground-truth checks in `tests/test_tools.py` that
reference real UCI patterns (dates, category names, a specific product's
sales gap) will need to be swapped for the patterns this generator
injects instead — they were written for whichever data source is
currently wired up, not both at once.
