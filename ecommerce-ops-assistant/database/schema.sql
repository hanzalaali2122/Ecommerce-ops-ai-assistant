-- =============================================================================
-- schema.sql
-- -----------------------------------------------------------------------------
-- This file defines the SQLite database structure for the Ecommerce Operations
-- Assistant. Think of it as the "filing cabinet" the whole project works out
-- of: every tool the AI model can call eventually boils down to a SELECT (or,
-- for approvals, an INSERT/UPDATE) against one of these tables.
--
-- The design follows the project brief's table list, adapted to real UCI
-- "Online Retail" data instead of a from-scratch synthetic generator:
--   customers, products, variants, orders, order_items, refunds, inventory,
--   inventory_movements, discount_codes, approval_requests, tool_runs
--
-- Why these tables exist, in plain language:
--   - customers / products / variants / orders / order_items: the normal
--     shape of any store's sales data. "Variants" exist because the brief
--     wants product and variant kept separate (e.g. a hoodie is a product,
--     "Hoodie, size M, black" is a variant) even though the UCI dataset
--     itself is flatter (one StockCode per row). We synthesize single-variant
--     products from UCI's StockCode/Description so the rest of the system
--     (which expects variants) works unchanged if you ever plug in a richer
--     dataset with real size/color variants.
--   - refunds: UCI represents a refund/cancellation as an invoice whose
--     number starts with "C" and has a negative quantity. We detect those
--     during loading and write them here as proper refund rows instead of
--     leaving them mixed into normal sales.
--   - inventory / inventory_movements: UCI has no stock-on-hand field at all
--     (it is a record of past transactions, not a live inventory system), so
--     these are synthesized from sales velocity with a fixed random seed,
--     clearly marked as synthetic. This lets Workflow B (replenishment
--     planning) work against something realistic.
--   - discount_codes: also synthetic, since UCI has no promo codes. A few are
--     generated and deliberately linked to a known date range so the
--     "promotion that raises order count but reduces margin" scenario the
--     brief asks for has a real, checkable answer.
--   - approval_requests / tool_runs: these start empty. approval_requests is
--     the human-in-the-loop inbox for discount/inventory actions proposed by
--     the assistant. tool_runs is the audit log: every tool call the model
--     makes gets one row here, which is what powers the "Investigation view"
--     in the brief.
-- =============================================================================

PRAGMA foreign_keys = ON;

-- ---------------------------------------------------------------------------
-- customers: one row per unique CustomerID seen in the source data.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS customers (
    customer_id     TEXT PRIMARY KEY,   -- UCI's CustomerID, kept as text (some ids have no numeric meaning)
    name            TEXT,               -- UCI has no names; we generate a placeholder display name
    email           TEXT,               -- synthesized placeholder email, clearly fake
    country         TEXT,               -- taken directly from UCI's Country column
    created_date    TEXT                -- date of this customer's first observed invoice
);

-- ---------------------------------------------------------------------------
-- products: one row per unique StockCode+Description combination.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS products (
    product_id      TEXT PRIMARY KEY,   -- derived from StockCode
    title           TEXT NOT NULL,      -- UCI's Description, cleaned up
    category        TEXT,               -- UCI has no category column; derived heuristically from the title
    status          TEXT NOT NULL DEFAULT 'active'  -- 'active' or 'discontinued' (set from recent sales activity)
);

-- ---------------------------------------------------------------------------
-- variants: in the real UCI data each StockCode is already a single sellable
-- unit, so each product gets exactly one variant. The column still exists
-- (and still carries price/cost) so every tool in the brief that reads
-- "variant_id" works the same way it would against a richer catalog.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS variants (
    variant_id      TEXT PRIMARY KEY,
    product_id      TEXT NOT NULL REFERENCES products(product_id),
    sku             TEXT,
    size            TEXT,               -- NULL for most rows; UCI doesn't carry size
    color           TEXT,               -- NULL for most rows; UCI doesn't carry color
    price           REAL NOT NULL,      -- most recent observed UnitPrice for this StockCode
    cost            REAL NOT NULL       -- synthesized: price * a random margin factor (clearly a model, not real cost data)
);

-- ---------------------------------------------------------------------------
-- orders: one row per UCI InvoiceNo (excluding cancellation invoices, which
-- go to `refunds` instead -- see build_database.py for that logic).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS orders (
    order_id        TEXT PRIMARY KEY,   -- UCI's InvoiceNo
    customer_id     TEXT REFERENCES customers(customer_id),  -- some UCI rows have no CustomerID (guest checkout)
    order_date      TEXT NOT NULL,      -- UCI's InvoiceDate, normalized to ISO 8601
    status          TEXT NOT NULL,      -- 'completed', 'cancelled' (see metrics.py for exact rules)
    currency        TEXT NOT NULL DEFAULT 'GBP',  -- UCI prices are in GBP
    subtotal        REAL NOT NULL,      -- sum of line items before discount
    discount_total  REAL NOT NULL DEFAULT 0,
    total            REAL NOT NULL       -- subtotal - discount_total
);

CREATE INDEX IF NOT EXISTS idx_orders_date ON orders(order_date);
CREATE INDEX IF NOT EXISTS idx_orders_customer ON orders(customer_id);

-- ---------------------------------------------------------------------------
-- order_items: one row per UCI invoice line (InvoiceNo + StockCode pair).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS order_items (
    order_item_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id        TEXT NOT NULL REFERENCES orders(order_id),
    variant_id      TEXT NOT NULL REFERENCES variants(variant_id),
    quantity        INTEGER NOT NULL,
    unit_price      REAL NOT NULL,
    discount        REAL NOT NULL DEFAULT 0   -- per-line discount amount applied, if any
);

CREATE INDEX IF NOT EXISTS idx_order_items_order ON order_items(order_id);
CREATE INDEX IF NOT EXISTS idx_order_items_variant ON order_items(variant_id);

-- ---------------------------------------------------------------------------
-- refunds: built from UCI's cancellation invoices (InvoiceNo starting "C").
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS refunds (
    refund_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id        TEXT REFERENCES orders(order_id),  -- best-effort match back to the original order; may be NULL
    variant_id      TEXT REFERENCES variants(variant_id),
    refund_date     TEXT NOT NULL,
    amount          REAL NOT NULL,
    reason          TEXT NOT NULL DEFAULT 'customer_cancellation'
);

CREATE INDEX IF NOT EXISTS idx_refunds_date ON refunds(refund_date);

-- ---------------------------------------------------------------------------
-- inventory: synthetic current stock snapshot, one row per variant.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS inventory (
    variant_id        TEXT PRIMARY KEY REFERENCES variants(variant_id),
    available_units   INTEGER NOT NULL,
    reorder_threshold INTEGER NOT NULL
);

-- ---------------------------------------------------------------------------
-- inventory_movements: synthetic log of stock changes (sales draw stock down,
-- restocks push it back up). Used only for narrative/audit realism; the
-- actual stockout-risk math in tools/inventory.py uses `inventory` +
-- recent `order_items` sales velocity, not this log.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS inventory_movements (
    movement_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    variant_id      TEXT NOT NULL REFERENCES variants(variant_id),
    quantity_change INTEGER NOT NULL,   -- negative for sales, positive for restocks
    reason          TEXT NOT NULL,      -- 'sale', 'restock', 'adjustment'
    occurred_at     TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_inv_mov_variant ON inventory_movements(variant_id);

-- ---------------------------------------------------------------------------
-- discount_codes: synthetic promo codes, one of which is deliberately
-- scheduled over a known window so the "promo raised orders but cut margin"
-- scenario can be verified against ground truth.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS discount_codes (
    code            TEXT PRIMARY KEY,
    percentage      REAL NOT NULL,
    start_date      TEXT NOT NULL,
    expiry_date     TEXT NOT NULL
);

-- ---------------------------------------------------------------------------
-- approval_requests: the human-in-the-loop inbox. propose_discount and
-- propose_inventory_alert INSERT here with status='pending'. A human (via
-- the approval API, never the model) flips status to 'approved' or
-- 'rejected'. Only an 'approved' row may ever be executed, and only once
-- (see app/main.py's idempotency check).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS approval_requests (
    request_id      TEXT PRIMARY KEY,   -- UUID, generated when proposed
    action          TEXT NOT NULL,      -- 'discount' or 'inventory_alert'
    payload         TEXT NOT NULL,      -- JSON blob: the exact parameters proposed
    status          TEXT NOT NULL DEFAULT 'pending',  -- pending | approved | rejected | executed
    requester       TEXT NOT NULL,      -- which conversation/user asked for this
    reviewer        TEXT,               -- who approved/rejected it
    created_at      TEXT NOT NULL,
    decided_at      TEXT,
    executed_at     TEXT
);

-- ---------------------------------------------------------------------------
-- tool_runs: the audit trail. Every single tool call the model makes --
-- whether it's a harmless read like get_sales_summary or a sensitive
-- propose_discount -- gets one row here with its arguments, duration, and
-- outcome. This is what the "Investigation view" in the brief reads from.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS tool_runs (
    run_id          TEXT PRIMARY KEY,   -- UUID
    request_id      TEXT NOT NULL,      -- groups all tool_runs from one /chat call together
    tool_name       TEXT NOT NULL,
    arguments       TEXT NOT NULL,      -- JSON blob of the arguments the model passed
    result_summary  TEXT,               -- small JSON summary of what came back (never raw PII dumps)
    status          TEXT NOT NULL,      -- 'success' | 'error' | 'blocked'
    duration_ms     INTEGER NOT NULL,
    started_at      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_tool_runs_request ON tool_runs(request_id);
