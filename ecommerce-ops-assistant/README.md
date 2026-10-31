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

```
database/
  schema.sql                   the SQLite schema
  build_database.py            CSV -> shop.db (run this to (re)build the DB)
  generate_stand_in_data.py    fallback: fabricates a stand-in CSV
  shop.db                      the built SQLite database (git-ignored-sized; rebuild if missing)
data/
  online_retail_raw.csv        the real UCI data, in the loader's expected shape
  convert_real_dataset.py      .xlsx -> the CSV above
  raw/                         the original real CSV + the archived stand-in CSV
metrics.py                     the one definition of revenue/margin/date-windows, imported everywhere
tools/                         every AI-callable (and a few human-only) function, one concern per file
  db.py                          shared SQLite connection helper
  validation.py                  all argument-checking rules, centralized
  catalog.py                     search_products, get_product_details, get_inventory
  orders.py                      get_order, get_customer_summary
  sales.py                       get_sales_summary, compare_sales_periods, get_product_performance, get_refund_summary
  inventory.py                   get_stockout_risk, calculate_reorder_quantity
  external.py                    get_exchange_rate (the one tool that calls outside the DB)
  approvals.py                   propose_discount, propose_inventory_alert, and the human-only decide/execute functions
  audit.py                       writes every tool call to tool_runs
  schemas.py                     TOOL_REGISTRY: the allowlist Gemini is ever permitted to call
app/
  agent.py                       the real Gemini tool-calling loop
  mock_agent.py                  a rule-based fallback that needs no API key
  main.py                        the FastAPI app (chat, investigations, approvals)
  auth.py                        simple role/user resolution from headers
  models.py                      Pydantic request/response shapes
tests/
  test_metrics.py, test_tools.py   the actual tests
  run_tests.py                     zero-dependency runner (works without pytest installed)
docs/
  data_profile.md                 real, discovered ground-truth patterns in the data
  profile_queries.sql             the exact SQL behind that document's numbers
  explained/                      a companion doc per source file, explaining what it does and why
```

## Setup

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Build the database from the real UCI data (already converted and
#    checked into data/online_retail_raw.csv -- this step just builds
#    shop.db from it)
python3 database/build_database.py

# 3. Run the tests
pytest tests/ -v
# -- or, if pytest isn't available in your environment --
python3 tests/run_tests.py
```

Both should report all tests passing (31 tests as of this build).

**Note:** `test_tools.py` runs against the live `database/shop.db`, and a
few tests (the approval-workflow ones) genuinely write rows to it —
`approval_requests`, `tool_runs`, and, in the idempotency test, one real
`discount_codes` row. This is intentional (it's really exercising the
same database code a live request would), but if you want a pristine
database afterward, just re-run `python3 database/build_database.py`.

### Using a different source file

If you want to re-derive `data/online_retail_raw.csv` from the original
`Online Retail.xlsx` yourself (or from a newer UCI export):

```bash
python3 data/convert_real_dataset.py "/path/to/Online Retail.xlsx"
python3 database/build_database.py
```

Or switch to fully synthetic, controllable test data instead:

```bash
python3 database/generate_stand_in_data.py
python3 database/build_database.py
```
(If you do this, re-derive the ground-truth test assertions in
`tests/test_tools.py` using `docs/data_profile.md`'s method — they're
currently pinned to the real data's own patterns.)

## Running the API and the frontend

```bash
uvicorn app.main:app --reload --port 8000
```

Then open **http://localhost:8000/** in a browser — `app/main.py` serves
`frontend/` (a small dependency-free chat UI, investigation trace viewer,
and approval inbox — see `docs/explained/frontend_explained.md`)
automatically at that address. FastAPI also gives you a free interactive
API explorer at **http://localhost:8000/docs**, useful for poking at
individual endpoints without the UI.

Works immediately with **no API key** — `/chat` automatically falls back
to the rule-based `app/mock_agent.py`, which calls the exact same real
tools and real database, just without free-form language understanding.

**Note on this environment specifically:** the sandbox this project was
built in has no outbound internet access to `pip install` anything
(confirmed — both `archive.ics.uci.edu` and PyPI are unreachable from
here), so `fastapi`/`uvicorn` could not be installed or the server
actually started *in this sandbox* to verify it visually. The frontend's
JavaScript was syntax-checked with `node --check`, and every backend
function it calls is covered by the passing test suite — but running
`uvicorn` and opening the page is something you'll need to do on your
own machine, where `pip install -r requirements.txt` can reach PyPI.

To enable the real Gemini-backed investigation loop:

```bash
export GEMINI_API_KEY="your-key-here"
uvicorn app.main:app --reload --port 8000
```

Then `GET /health` will report `"agent_mode": "gemini"` instead of
`"mock"`.

### Trying the four workflows

```bash
# Workflow A: sales decline investigation
curl -X POST localhost:8000/chat -H "Content-Type: application/json" \
  -d '{"question": "Compare the last seven complete days with the previous seven. What drove the revenue change?"}'

# Workflow B: replenishment planning
curl -X POST localhost:8000/chat -H "Content-Type: application/json" \
  -d '{"question": "Which products may run out within two weeks, and how much should we reorder?"}'

# Workflow C: investigate one order (use a real order_id from your database)
curl -X POST localhost:8000/chat -H "Content-Type: application/json" \
  -d '{"question": "Check order 536365. What was purchased, and is it refunded?"}'

# Workflow D: propose a discount (needs GEMINI_API_KEY, or call the tool directly)
curl -X POST "localhost:8000/tools/propose_discount" \
  -H "Content-Type: application/json" -H "X-User-Role: manager" \
  -d '{"product_ids": ["85123A"], "percentage": 10, "start_date": "2030-01-01", "end_date": "2030-01-07"}'

# See every tool call behind one /chat response
curl localhost:8000/investigations/{request_id}

# The approval inbox
curl localhost:8000/approvals
curl -X POST "localhost:8000/approvals/{request_id}/approve" -H "X-User-Role: manager"
curl -X POST "localhost:8000/approvals/{request_id}/execute" -H "X-User-Role: manager"
```

Role is set via the `X-User-Role` header (`analyst` / `support` /
`manager`, defaults to `analyst`); user via `X-User-Id` (defaults to
`demo-user`). This is a deliberately simple stand-in for real auth — see
`docs/explained/app/auth_explained.md`.

## What's implemented vs. what's next

**Done:** database generator (on real data) with documented, verified
business patterns; all eleven read-only tools plus the two propose-only
write tools, unit tested independently of any AI model (31/31 passing);
the Gemini tool-calling loop with execution limits, role checks, and full
audit logging; a rule-based fallback that needs no API key; the FastAPI
layer with chat, investigation, and approval endpoints; the
human-approval boundary with idempotent execution.

**Not yet built:** the brief's 50-question fixed evaluation dataset and
metrics report; a live order/inventory simulator; optional real Shopify
integration; PostgreSQL migration.

## A note on honesty in this codebase

Two places in this project deliberately report failure rather than
invent a plausible-looking answer, because the brief's own evaluation
table specifically tests for this: `tools/external.py`'s
`get_exchange_rate` returns an explicit "unavailable" result (never a
fabricated rate) if the live exchange-rate API can't be reached, and
`docs/data_profile.md` #4 is careful to call a real 33-day sales gap an
*observed gap*, not a *proven stockout* — the data doesn't support a
stronger claim than that.
