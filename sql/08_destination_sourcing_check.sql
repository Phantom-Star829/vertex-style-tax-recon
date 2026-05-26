-- 08_destination_sourcing_check.sql
--
-- BUSINESS QUESTION:
--   For interstate sales (dealer in one state, ship-to in another),
--   did the POS source the tax to the right state? Wrong sourcing
--   means we sent the cash to the wrong DOR; we now owe one state and
--   need to file a refund claim with the other.
--
-- WHAT THIS QUERY DOES:
--   Filters to interstate transactions, joins to the engine's recon
--   table, and shows when the POS appears to have applied the dealer
--   state's rate rather than the ship-to state's. Includes the
--   side-by-side rate columns so the answer is visible at a glance.
--
-- WHY AN INDIRECT TAX ANALYST RUNS THIS:
--   Sourcing errors are quiet but expensive. They don't usually trip
--   the POS exception report because both numbers look reasonable.
--   This query is how you find them at month-end.

WITH interstate AS (
    SELECT
        t.transaction_id,
        t.sale_date,
        t.dealer_state,
        t.ship_to_state,
        t.sale_price,
        t.trade_in_value,
        t.tax_collected,
        rd.tax_owed,
        rd.rate_applied,
        rd.variance,
        rd.category
    FROM transactions t
    JOIN recon_detail rd USING(transaction_id)
    WHERE t.dealer_state != t.ship_to_state
)
SELECT
    transaction_id,
    sale_date,
    dealer_state,
    ship_to_state,
    ROUND(sale_price, 2)        AS sale_price,
    ROUND(tax_collected, 2)     AS tax_collected,
    ROUND(tax_owed, 2)          AS tax_owed,
    ROUND(variance, 2)          AS variance,
    category
FROM interstate
WHERE category IN ('sourcing_error', 'rate_mismatch')
ORDER BY ABS(variance) DESC;
