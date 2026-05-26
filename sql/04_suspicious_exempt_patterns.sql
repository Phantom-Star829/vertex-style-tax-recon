-- 04_suspicious_exempt_patterns.sql
--
-- BUSINESS QUESTION:
--   Is any single customer or dealer using exemption claims at a
--   suspicious rate? A buyer with 10+ exempt purchases in 30 days is
--   either a legitimate fleet account (good, we want the cert on file)
--   or a fraud pattern (bad, we want the controller to look).
--
-- WHAT THIS QUERY DOES:
--   We don't have a customer_id column on the transactions table
--   (this is a simplified demo). Instead we proxy by exempt_cert_id
--   plus dealer_state, then use a CTE + window function to count
--   how many exempt purchases occurred within a rolling 30-day window
--   per cert ID. Anything 10 or more bubbles up.
--
-- WHY AN INDIRECT TAX ANALYST RUNS THIS:
--   Fraud and risk detection. State revenue departments share
--   information; if a cert ID shows up in a tax exposure case at
--   another retailer, our team wants to know before the auditor does.

WITH exempt_txns AS (
    SELECT
        exempt_cert_id,
        dealer_state,
        sale_date,
        sale_price
    FROM transactions
    WHERE customer_exempt_flag = 1
      AND exempt_cert_id IS NOT NULL
      AND TRIM(exempt_cert_id) != ''
),
windowed AS (
    SELECT
        e.exempt_cert_id,
        e.dealer_state,
        e.sale_date,
        COUNT(*) OVER (
            PARTITION BY e.exempt_cert_id
            ORDER BY date(e.sale_date)
            RANGE BETWEEN 30 PRECEDING AND CURRENT ROW
        )                                        AS purchases_in_last_30d,
        SUM(e.sale_price) OVER (
            PARTITION BY e.exempt_cert_id
            ORDER BY date(e.sale_date)
            RANGE BETWEEN 30 PRECEDING AND CURRENT ROW
        )                                        AS dollars_in_last_30d
    FROM exempt_txns e
)
SELECT
    exempt_cert_id,
    dealer_state,
    sale_date,
    purchases_in_last_30d,
    ROUND(dollars_in_last_30d, 2) AS dollars_in_last_30d
FROM windowed
WHERE purchases_in_last_30d >= 10
ORDER BY purchases_in_last_30d DESC, dollars_in_last_30d DESC;
