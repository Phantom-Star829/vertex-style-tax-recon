-- 05_tradein_credit_audit.sql
--
-- BUSINESS QUESTION:
--   Did the POS apply trade-in credits correctly in each state? CA
--   does NOT allow trade-in credit on vehicles. IL caps the credit at
--   $10,000. TX, FL, GA, AZ, NC, OH, PA, NY allow full credit. The
--   POS should mirror those rules.
--
-- WHAT THIS QUERY DOES:
--   Joins transactions to recon_detail and filters to the category
--   we flagged as 'tradein_credit_error'. For each, shows what the
--   collected tax actually was vs. what the engine says it should be.
--   The "would_have_been_correct_if_full_credit" column proves the
--   theory: if you re-run with the credit applied, you land on the
--   engine number.
--
-- WHY AN INDIRECT TAX ANALYST RUNS THIS:
--   Tells the POS team which deals to re-post a credit memo on, and
--   tells the controller which dollar amount to claim back from the
--   customer or write off depending on materiality.

SELECT
    t.transaction_id,
    t.sale_date,
    t.ship_to_state,
    ROUND(t.sale_price, 2)                                     AS sale_price,
    ROUND(t.trade_in_value, 2)                                 AS trade_in_value,
    ROUND(rd.tax_collected, 2)                                 AS tax_collected,
    ROUND(rd.tax_owed, 2)                                      AS tax_owed,
    ROUND(rd.variance, 2)                                      AS variance,
    ROUND(t.sale_price * rd.rate_applied, 2)                   AS tax_if_no_credit,
    ROUND((t.sale_price - t.trade_in_value) * rd.rate_applied, 2)
                                                               AS tax_if_full_credit
FROM transactions t
JOIN recon_detail rd USING(transaction_id)
WHERE rd.category = 'tradein_credit_error'
ORDER BY ABS(rd.variance) DESC;
