"""
tools/catalog.py
--------------------------------------------------------------------------
Tools for looking up products, variants, and current stock.
These are pure reads -- no approval needed, nothing is ever written here.

Each function:
  1. Validates its own arguments (never trusts the model's input blindly).
  2. Runs ONE parameterized SQL query (never string-concatenated SQL).
  3. Returns a small plain dict/list -- never thousands of raw rows -- so
     the model gets something it can reason about, not something it has
     to do arithmetic over by hand.
"""

from tools.db import get_connection, rows_to_dicts
from tools.validation import require_non_empty_string, validate_limit, ToolValidationError


def search_products(query: str, category: str | None = None, limit: int | None = None) -> dict:
    """
    Find products by a text search over their title, optionally narrowed
    to one category. Returns product-level summaries (not individual
    variants) so the model can identify the right product_id before
    calling get_product_details for the full picture.
    """
    query = require_non_empty_string(query, "query")
    limit = validate_limit(limit, default=20)

    sql = """
        SELECT p.product_id, p.title, p.category, p.status,
               MIN(v.price) AS min_price, MAX(v.price) AS max_price,
               COUNT(v.variant_id) AS variant_count
        FROM products p
        JOIN variants v ON v.product_id = p.product_id
        WHERE p.title LIKE ?
    """
    params = [f"%{query}%"]
    if category:
        sql += " AND p.category = ?"
        params.append(category)
    sql += " GROUP BY p.product_id ORDER BY p.title LIMIT ?"
    params.append(limit)

    conn = get_connection()
    try:
        rows = conn.execute(sql, params).fetchall()
    finally:
        conn.close()

    return {"query": query, "category": category, "count": len(rows), "products": rows_to_dicts(rows)}


def get_product_details(product_id: str) -> dict:
    """Full detail for one product: its metadata plus every variant."""
    product_id = require_non_empty_string(product_id, "product_id")

    conn = get_connection()
    try:
        product = conn.execute(
            "SELECT product_id, title, category, status FROM products WHERE product_id = ?",
            (product_id,),
        ).fetchone()
        if product is None:
            return {"error": "not_found", "message": f"No product with id {product_id!r}."}

        variants = conn.execute(
            "SELECT variant_id, sku, size, color, price, cost FROM variants WHERE product_id = ?",
            (product_id,),
        ).fetchall()
    finally:
        conn.close()

    return {"product": dict(product), "variants": rows_to_dicts(variants)}


def get_inventory(variant_id: str) -> dict:
    """Current available stock and reorder threshold for one variant."""
    variant_id = require_non_empty_string(variant_id, "variant_id")

    conn = get_connection()
    try:
        row = conn.execute(
            """
            SELECT i.variant_id, i.available_units, i.reorder_threshold,
                   v.product_id, p.title AS product_title
            FROM inventory i
            JOIN variants v ON v.variant_id = i.variant_id
            JOIN products p ON p.product_id = v.product_id
            WHERE i.variant_id = ?
            """,
            (variant_id,),
        ).fetchone()
    finally:
        conn.close()

    if row is None:
        return {"error": "not_found", "message": f"No inventory record for variant {variant_id!r}."}
    result = dict(row)
    result["below_threshold"] = result["available_units"] <= result["reorder_threshold"]
    result["note"] = "available_units and reorder_threshold are synthesized (UCI source data has no live stock feed)."
    return result
