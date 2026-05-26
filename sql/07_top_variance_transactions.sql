-- 07_top_variance_transactions.sql
--
-- BUSINESS QUESTION:
--   Which individual transactions account for the biggest dollar
--   variances? Materiality matters. Five $1 variances can stay on the
--   wash; one $1,500 variance needs to be cleared before the books
--   close.
--
-- WHAT THIS QUERY DOES:
--   Uses ROW_NUMBER() partitioned by state to rank the top 5 highest-
--   absolute-variance transactions per state. Returns one consolidated
--   list the analyst can chase down today.
--
-- WHY AN INDIRECT TAX ANALYST RUNS THIS:
--   Direct work queue. Each row is a transaction the analyst needs to
--   open in the source system (Oracle Cloud ERP or POS) and confirm
--   the rate, sourcing, and trade-in setup. Drives the morning
--   action list during close week.

WITH ranked AS (
    SELECT
        transaction_id,
        sale_date,
        taxing_state,
        ROUND(sale_price, 2)    AS sale_price,
        ROUND(tax_owed, 2)      AS tax_owed,
        ROUND(tax_collected, 2) AS tax_collected,
        ROUND(variance, 2)      AS variance,
        category,
        ROW_NUMBER() OVER (
            PARTITION BY taxing_state
            ORDER BY ABS(variance) DESC
        ) AS rank_in_state
    FROM recon_detail
    WHERE category != 'clean'
)
SELECT *
FROM ranked
WHERE rank_in_state <= 5
ORDER BY taxing_state, rank_in_state;
