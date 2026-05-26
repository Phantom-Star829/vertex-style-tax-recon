-- 03_missing_exemption_certs.sql
--
-- BUSINESS QUESTION:
--   Which exempt transactions are missing a valid resale or exemption
--   certificate? Each one is an audit exposure: state auditor pulls
--   the file, no cert on hand, the exemption is disallowed and the
--   tax (plus penalties) is owed.
--
-- WHAT THIS QUERY DOES:
--   Anti-join pattern: pull exempt-flagged transactions that either
--   have no cert ID at all or have a cert ID that is empty/whitespace.
--   The dollar exposure column quantifies how much tax we'd owe if
--   each one were disallowed.
--
-- WHY AN INDIRECT TAX ANALYST RUNS THIS:
--   This is the single highest-impact query in the file. Missing
--   exemption certificates are the #1 audit finding in retail.
--   Catching them at month-end (instead of three years later in audit)
--   means the team can chase the customer for the cert while the deal
--   is still fresh.

SELECT
    t.transaction_id,
    t.sale_date,
    t.ship_to_state,
    t.dealer_state,
    ROUND(t.sale_price, 2)                                 AS sale_price,
    t.customer_exempt_flag,
    t.exempt_cert_id,
    ROUND(rd.tax_owed, 2)                                  AS tax_at_risk
FROM transactions t
LEFT JOIN recon_detail rd USING(transaction_id)
WHERE t.customer_exempt_flag = 1
  AND (t.exempt_cert_id IS NULL OR TRIM(t.exempt_cert_id) = '')
ORDER BY t.sale_price DESC;
