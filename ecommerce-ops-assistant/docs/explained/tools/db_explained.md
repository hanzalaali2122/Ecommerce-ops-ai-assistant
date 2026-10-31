# `tools/db.py` — explained

**What it is:** the smallest file in the project, and the one every
other tool file depends on. It answers one question — "how do I open the
database?" — in exactly one place.

## What it provides

```python
def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn
```

Two small but important choices live here:

- **`row_factory = sqlite3.Row`** — without this, a query result row
  behaves like a plain tuple (`row[0]`, `row[1]`...). With it, a row
  behaves like a dictionary (`row["revenue"]`, `row["customer_id"]`).
  Every tool function in the project relies on this to turn SQL results
  into clean JSON-shaped dicts without needing a full ORM.
- **`PRAGMA foreign_keys = ON`** — SQLite has foreign-key *enforcement*
  turned off by default, surprisingly. Turning it on here means a bug
  that tries to insert, say, an `order_items` row pointing at a
  `variant_id` that doesn't exist fails loudly and immediately, instead
  of silently writing bad data that some tool discovers much later.

`rows_to_dicts(rows)` is a one-line helper (`[dict(r) for r in rows]`)
used everywhere a tool returns a list of rows, so every tool file doesn't
repeat that same list comprehension.

## Why every tool opens its own short-lived connection

Each tool function calls `get_connection()`, does its query, and calls
`conn.close()` in a `finally` block — rather than one connection being
shared and held open across a whole request. For a read-heavy workload
like this one (mostly `SELECT`s, a handful of small `INSERT`s), SQLite
handles many short connections fine, and this avoids any risk of one
slow request holding a connection (and a lock) open while others wait.

## How this connects to the rest of the project

Every file in `tools/` imports `get_connection` and/or `rows_to_dicts`
from here. It is the only file that knows the literal path to
`database/shop.db` (`DB_PATH`, computed relative to this file's own
location so it works no matter what directory you run Python from).
