-- 02_variance_by_state_month.sql
--
-- BUSINESS QUESTION:
--   Where is most of our tax variance dollar-concentrated by month?
--   Should we focus this close cycle on Texas in March, or New York
--   in July?
--
-- WHAT THIS QUERY DOES:
--   GROUP BY rollup across state and month. Adds a percentage-of-
--   absolute-variance column so the analyst can rank by impact, not
--   by direction.
--
-- WHY AN INDIRECT TAX ANALYST RUNS THIS:
--   Prioritization. Manager-of-tax wants to know which state-month
--   pairs to investigate first. The biggest absolute variances drive
--   the work queue.

WITH agg AS (
    SELECT
        taxing_state,
        substr(sale_date, 1, 7)        AS period,
        COUNT(*)                       AS txn_count,
        ROUND(SUM(tax_owed), 2)        AS tax_owed,
        ROUND(SUM(tax_collected), 2)   AS tax_collected,
        ROUND(SUM(variance), 2)        AS net_variance,
        ROUND(SUM(ABS(variance)), 2)   AS abs_variance
    FROM recon_detail
    GROUP BY taxing_state, period
)
SELECT
    taxing_state,
    period,
    txn_count,
    tax_owed,
    tax_collected,
    net_variance,
    abs_variance,
    ROUND(100.0 * abs_variance / NULLIF(SUM(abs_variance) OVER (), 0), 2)
        AS pct_of_total_abs_variance
FROM agg
ORDER BY abs_variance DESC;
