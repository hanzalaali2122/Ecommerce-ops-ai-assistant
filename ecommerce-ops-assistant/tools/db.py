"""
tools/db.py
--------------------------------------------------------------------------
A tiny shared helper so every tool file opens the database the same way,
instead of each one repeating connection/row-factory boilerplate.

get_connection() returns a sqlite3.Connection with:
  - row_factory = sqlite3.Row, so query results behave like dictionaries
    (row["revenue"] instead of row[0]) -- this is what lets the tool
    functions turn SQL results into clean JSON without a separate ORM.
  - foreign_keys turned on, so a bug that tries to insert an order_item
    pointing at a variant that doesn't exist fails loudly instead of
    silently corrupting data.

Every tool function opens its own short-lived connection and closes it
before returning. SQLite handles many short connections fine for a
read-heavy workload like this one; we are not holding a connection open
across a whole /chat request.
"""

import os
import sqlite3

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "database", "shop.db")


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def rows_to_dicts(rows):
    return [dict(r) for r in rows]
