# Ecommerce Operations AI Assistant

A store-operations assistant that investigates sales, inventory,
customers, and orders using real UK online-retail transaction data, and
prepares sensitive actions (discounts, inventory-threshold changes) for
human approval rather than executing them itself.

This builds out the project brief's milestones 1–2 (database generator
with known business patterns, and read-only tools tested without an AI
model) on top of real data, plus the full tool-calling loop, FastAPI
layer, and approval workflow (milestones 3–7) that were already in place
in this project directory when this pass started.

**If you're trying to understand the code, not just run it:** every
source file has a matching plain-English companion doc in
`docs/explained/`, mirroring the project's own folder structure (e.g.
`tools/sales.py` → `docs/explained/tools/sales_explained.md`). Start
there, or with `docs/data_profile.md` for what the data actually shows.

## What makes this data real, not synthetic

The brief originally called for a from-scratch synthetic data generator.
This project instead uses the real **[UCI "Online Retail" dataset](https://archive.ics.uci.edu/dataset/352/online-retail)**
— 541,909 real transaction rows from a UK-based online gift retailer,
December 2010 to December 2011. The data's real messiness (guest
checkouts, cancellations, inconsistent text) is handled directly, and the
handful of things the real data genuinely doesn't contain (current stock
levels, product costs, promo codes) are clearly synthesized and labeled
as such everywhere they're used. See `docs/data_profile.md` for the real,
*discovered* business patterns in this data (an unusual one: this
retailer has zero Saturday sales in the entire dataset) that the test
suite checks the tools against — in place of the brief's originally
envisioned *injected* synthetic patterns.

The original fully-synthetic generator (`database/generate_stand_in_data.py`)
is still in the project as a fallback, documented in its own explained
file, for anyone who wants fully controllable test data instead.

## Project layout
