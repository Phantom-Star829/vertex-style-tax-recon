"""reconcile.py

Compare what the POS booked (tax_collected) against what the engine
says should have been booked (tax_owed), and categorize each variance.

OUTPUT:
  data/recon_detail.csv     one row per transaction with variance + category
  data/recon_summary.csv    aggregated by state x category

CATEGORIES (in order of precedence):
  1. clean                     within rounding tolerance, no action needed
  2. missing_exemption_cert    exempt flag set but cert blank or missing
  3. tradein_credit_error      credit was due but POS taxed the gross
  4. sourcing_error            POS taxed at the dealer-state rate when
                               destination sourcing applied (or vice versa)
  5. rate_mismatch             rate applied differs from the engine rate
  6. unknown                   variance exists but doesn't match a rule

This is the monthly close workflow a Staff Accountant runs: pull the
month's transactions, compute the engine's view, diff against the GL
(or POS feed), categorize the gap, and route exceptions to the right
team.
"""

from __future__ import annotations

import csv
import sqlite3
from decimal import Decimal
from pathlib import Path

from .tax_engine import STATE_RULES, compute_tax, ROUNDING_TOLERANCE_USD, _money

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "sales.db"
DETAIL_CSV = Path(__file__).resolve().parent.parent / "output" / "recon_detail.csv"
SUMMARY_CSV = Path(__file__).resolve().parent.parent / "output" / "recon_summary.csv"


def _categorize(
    sale_price: Decimal,
    trade_in_value: Decimal,
    dealer_state: str,
    ship_to_state: str,
    customer_exempt_flag: bool,
    exempt_cert_id: str | None,
    tax_collected: Decimal,
    tax_owed: Decimal,
    rate_applied: Decimal,
    taxing_state: str,
) -> str:
    variance = (tax_collected - tax_owed)
    if abs(variance) <= ROUNDING_TOLERANCE_USD:
        return "clean"

    # Missing exemption cert: POS treated as exempt (zero tax) but cert is blank
    if customer_exempt_flag and (not exempt_cert_id or not str(exempt_cert_id).strip()):
        if tax_collected == Decimal("0.00"):
            return "missing_exemption_cert"

    # Trade-in credit error: POS taxed the gross price as if no credit applied
    if trade_in_value > 0 and rate_applied > 0:
        gross_tax = _money(sale_price * rate_applied)
        if abs(tax_collected - gross_tax) <= ROUNDING_TOLERANCE_USD and tax_owed < gross_tax:
            return "tradein_credit_error"

    # Sourcing error: POS used the dealer state's rate when destination
    # rules required the ship-to state, or vice versa
    if dealer_state != taxing_state:
        dealer_rule = STATE_RULES.get(dealer_state)
        if dealer_rule:
            # what tax would have been if dealer-state rule were used
            dealer_credit = trade_in_value if dealer_rule["trade_in_credit"] == "full" else Decimal("0")
            dealer_base = max(sale_price - dealer_credit, Decimal("0"))
            dealer_tax = _money(dealer_base * dealer_rule["rate"])
            if abs(tax_collected - dealer_tax) <= ROUNDING_TOLERANCE_USD:
                return "sourcing_error"

    # Rate mismatch: the implied rate on the collected side differs from engine rate
    base_for_implied = (
        max(sale_price - trade_in_value, Decimal("0"))
        if STATE_RULES.get(taxing_state, {}).get("trade_in_credit") == "full"
        else sale_price
    )
    if base_for_implied > 0:
        implied_rate = (tax_collected / base_for_implied).quantize(Decimal("0.0001"))
        if abs(implied_rate - rate_applied) >= Decimal("0.005"):
            return "rate_mismatch"

    return "unknown"


def run() -> tuple[Path, Path]:
    if not DB_PATH.exists():
        raise FileNotFoundError(
            f"{DB_PATH} not found. Run `python -m src.generate_data` first."
        )

    DETAIL_CSV.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM transactions").fetchall()

    detail: list[dict] = []
    for r in rows:
        result = compute_tax(
            transaction_id=r["transaction_id"],
            sale_price=r["sale_price"],
            trade_in_value=r["trade_in_value"],
            dealer_state=r["dealer_state"],
            ship_to_state=r["ship_to_state"],
            customer_exempt_flag=bool(r["customer_exempt_flag"]),
            exempt_cert_id=r["exempt_cert_id"],
        )
        tax_collected = Decimal(str(r["tax_collected"]))
        variance = _money(tax_collected - result.tax_owed)
        category = _categorize(
            sale_price=Decimal(str(r["sale_price"])),
            trade_in_value=Decimal(str(r["trade_in_value"])),
            dealer_state=r["dealer_state"],
            ship_to_state=r["ship_to_state"],
            customer_exempt_flag=bool(r["customer_exempt_flag"]),
            exempt_cert_id=r["exempt_cert_id"],
            tax_collected=tax_collected,
            tax_owed=result.tax_owed,
            rate_applied=result.rate_applied,
            taxing_state=result.taxing_state,
        )
        detail.append({
            "transaction_id": r["transaction_id"],
            "sale_date": r["sale_date"],
            "taxing_state": result.taxing_state,
            "rate_applied": float(result.rate_applied),
            "sale_price": r["sale_price"],
            "trade_in_value": r["trade_in_value"],
            "taxable_base": float(result.taxable_base),
            "tax_owed": float(result.tax_owed),
            "tax_collected": r["tax_collected"],
            "variance": float(variance),
            "category": category,
        })

    # Persist recon_detail rows back into SQLite for the SQL showcase files
    conn.execute("DROP TABLE IF EXISTS recon_detail;")
    conn.execute("""
        CREATE TABLE recon_detail (
            transaction_id  TEXT PRIMARY KEY,
            sale_date       TEXT NOT NULL,
            taxing_state    TEXT NOT NULL,
            rate_applied    REAL NOT NULL,
            sale_price      REAL NOT NULL,
            trade_in_value  REAL NOT NULL,
            taxable_base    REAL NOT NULL,
            tax_owed        REAL NOT NULL,
            tax_collected   REAL NOT NULL,
            variance        REAL NOT NULL,
            category        TEXT NOT NULL
        );
    """)
    conn.executemany(
        """
        INSERT INTO recon_detail
        (transaction_id, sale_date, taxing_state, rate_applied, sale_price,
         trade_in_value, taxable_base, tax_owed, tax_collected, variance, category)
        VALUES
        (:transaction_id, :sale_date, :taxing_state, :rate_applied, :sale_price,
         :trade_in_value, :taxable_base, :tax_owed, :tax_collected, :variance, :category)
        """,
        detail,
    )
    conn.commit()

    # write detail csv
    with DETAIL_CSV.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(detail[0].keys()))
        writer.writeheader()
        writer.writerows(detail)

    # build summary by state x category
    summary_rows = conn.execute("""
        SELECT taxing_state,
               category,
               COUNT(*)            AS txn_count,
               ROUND(SUM(variance), 2) AS total_variance,
               ROUND(SUM(tax_owed), 2) AS total_tax_owed,
               ROUND(SUM(tax_collected), 2) AS total_tax_collected
        FROM recon_detail
        GROUP BY taxing_state, category
        ORDER BY taxing_state, category;
    """).fetchall()

    with SUMMARY_CSV.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "taxing_state", "category", "txn_count",
            "total_variance", "total_tax_owed", "total_tax_collected",
        ])
        for row in summary_rows:
            writer.writerow([row["taxing_state"], row["category"], row["txn_count"],
                             row["total_variance"], row["total_tax_owed"], row["total_tax_collected"]])

    conn.close()
    print(f"Wrote {len(detail):,} recon rows to {DETAIL_CSV}")
    print(f"Wrote variance summary to {SUMMARY_CSV}")
    return DETAIL_CSV, SUMMARY_CSV


if __name__ == "__main__":
    run()
