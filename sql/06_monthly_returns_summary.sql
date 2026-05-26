-- 06_monthly_returns_summary.sql
--
-- BUSINESS QUESTION:
--   What does each state's monthly sales tax return need to show?
--   Most state returns ask for: gross sales, exempt sales, taxable
--   sales, tax due. This produces those four columns per state per
--   month, ready to paste into the return prep workbook.
--
-- WHAT THIS QUERY DOES:
--   Groups transactions by ship_to_state and YYYY-MM, then computes
--   each return line item. Uses CASE WHEN to split gross into exempt
--   vs. taxable. Joins to recon_detail to pull the engine's tax_owed
--   figure (the auditable number, not the POS one).
--
-- WHY AN INDIRECT TAX ANALYST RUNS THIS:
--   Returns preparation. This is roughly what you'd export, audit
--   one more time, and then key into the state portal or hand to the
--   tax return prep team.

SELECT
    t.ship_to_state                                                AS state,
    substr(t.sale_date, 1, 7)                                      AS period,
    COUNT(*)                                                       AS txn_count,
    ROUND(SUM(t.sale_price), 2)                                    AS gross_sales,
    ROUND(SUM(CASE WHEN t.customer_exempt_flag = 1
                   THEN t.sale_price ELSE 0 END), 2)               AS exempt_sales,
    ROUND(SUM(CASE WHEN t.customer_exempt_flag = 0
                   THEN t.sale_price ELSE 0 END), 2)               AS taxable_sales,
    ROUND(SUM(rd.tax_owed), 2)                                     AS tax_due,
    ROUND(SUM(rd.tax_collected), 2)                                AS tax_collected_pos,
    ROUND(SUM(rd.variance), 2)                                     AS recon_variance
FROM transactions t
JOIN recon_detail rd USING(transaction_id)
GROUP BY state, period
ORDER BY state, period;
