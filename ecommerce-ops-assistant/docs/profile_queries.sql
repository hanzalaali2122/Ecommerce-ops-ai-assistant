-- docs/profile_queries.sql
-- --------------------------------------------------------------------------
-- The exact queries behind the numbers in docs/data_profile.md. Run with:
--     sqlite3 database/shop.db < docs/profile_queries.sql
-- after building the database (python3 database/build_database.py).

.headers on
.mode column

.print '--- 1. Orders and revenue by day of week (0=Sunday .. 6=Saturday) ---'
SELECT strftime('%w', order_date) AS day_of_week,
       COUNT(*) AS orders,
       ROUND(SUM(total), 2) AS revenue
FROM orders
WHERE status = 'completed'
GROUP BY day_of_week
ORDER BY day_of_week;

.print ''
.print '--- 2. Refund rate by category ---'
SELECT p.category,
       COUNT(DISTINCT r.refund_id) AS refunds,
       COUNT(DISTINCT oi.order_id) AS orders_in_category,
       ROUND(1.0 * COUNT(DISTINCT r.refund_id) / NULLIF(COUNT(DISTINCT oi.order_id), 0), 4) AS refund_rate
FROM products p
JOIN variants v ON v.product_id = p.product_id
LEFT JOIN order_items oi ON oi.variant_id = v.variant_id
LEFT JOIN refunds r ON r.variant_id = v.variant_id
GROUP BY p.category
ORDER BY refund_rate DESC;

.print ''
.print '--- 3. Average order value: one-time vs loyal (5+ order) customers ---'
WITH per_customer AS (
    SELECT customer_id, COUNT(*) AS order_count, AVG(total) AS aov
    FROM orders
    WHERE status = 'completed' AND customer_id IS NOT NULL
    GROUP BY customer_id
)
SELECT
    CASE WHEN order_count = 1 THEN 'one_time' ELSE 'loyal_5_plus' END AS customer_group,
    COUNT(*) AS customers,
    ROUND(AVG(aov), 2) AS avg_order_value
FROM per_customer
WHERE order_count = 1 OR order_count >= 5
GROUP BY customer_group;

.print ''
.print '--- 4. The known observed sales gap: ALARM CLOCK BAKELIKE GREEN (22726-V1) ---'
SELECT o.order_date, oi.quantity
FROM order_items oi
JOIN orders o ON o.order_id = oi.order_id
WHERE oi.variant_id = '22726-V1' AND o.status = 'completed'
  AND o.order_date BETWEEN '2011-04-01' AND '2011-07-15'
ORDER BY o.order_date;
