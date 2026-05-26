-- 01_running_tax_liability.sql
--
-- BUSINESS QUESTION:
--   For each state, what does our cumulative tax liability look like
--   day by day across the year? At the end of any given week, how
--   close are we to the monthly remittance number?
--
-- WHAT THIS QUERY DOES:
--   Uses a window function (SUM OVER) to compute a running total of
--   tax_owed per state, ordered by sale_date. The result is a
--   timeline that an analyst can drop into Excel and chart.
--
-- WHY AN INDIRECT TAX ANALYST RUNS THIS:
--   Helps forecast cash needed for the monthly tax payment. Also
--   catches anomalies: if the cumulative line jumps unexpectedly on
--   a single day, that day is worth opening.

SELECT
    taxing_state,
    sale_date,
    ROUND(tax_owed, 2)                                                 AS daily_tax_owed,
    ROUND(SUM(tax_owed) OVER (
        PARTITION BY taxing_state
        ORDER BY sale_date
        ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
    ), 2)                                                              AS cumulative_tax_owed,
    ROUND(AVG(tax_owed) OVER (
        PARTITION BY taxing_state
        ORDER BY sale_date
        ROWS BETWEEN 6 PRECEDING AND CURRENT ROW
    ), 2)                                                              AS rolling_7day_avg
FROM recon_detail
ORDER BY taxing_state, sale_date;
