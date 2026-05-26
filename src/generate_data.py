"""generate_data.py

Generate 5,000 synthetic used-vehicle sales transactions and load
them into a local SQLite database at data/sales.db.

WHY synthetic data:
  A portfolio project can't ship real customer data. The generator
  intentionally introduces realistic noise into the POS tax_collected
  field, so the reconciliation engine downstream has variances to find.

WHAT THE NOISE LOOKS LIKE (so reviewers know it's intentional):
  - About 8% of transactions have the wrong rate applied (rate mismatch).
  - About 4% of transactions claim an exemption with a blank cert ID
    (missing exemption cert).
  - About 3% of transactions ignore the trade-in credit when they
    shouldn't (trade-in credit error).
  - About 2% of transactions use origin sourcing in a destination state
    (sourcing error).
  - Remaining ~83% are clean.

This produces a recon workload that looks like what a Staff Accountant
might actually see during a month-end close.
"""

from __future__ import annotations

import random
import sqlite3
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from .tax_engine import STATE_RULES, compute_tax, _money

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "sales.db"
TXN_COUNT = 5000
SEED = 42

# Approximate ZIP buckets per state (for show; not validated)
ZIP_BUCKETS = {
    "TX": ("75001", "78799"),
    "FL": ("32004", "34997"),
    "CA": ("90001", "96162"),
    "GA": ("30002", "39901"),
    "AZ": ("85001", "86556"),
    "NC": ("27006", "28909"),
    "OH": ("43001", "45999"),
    "PA": ("15001", "19640"),
    "IL": ("60001", "62999"),
    "NY": ("10001", "14975"),
}

STATES = list(STATE_RULES.keys())


def _random_zip(state: str, rng: random.Random) -> str:
    lo, hi = ZIP_BUCKETS[state]
    return str(rng.randint(int(lo), int(hi))).zfill(5)


def _random_date(rng: random.Random) -> str:
    """A 2025 calendar-year date string YYYY-MM-DD."""
    start = date(2025, 1, 1)
    end = date(2025, 12, 31)
    delta = (end - start).days
    return (start + timedelta(days=rng.randint(0, delta))).isoformat()


def _random_sale_price(rng: random.Random) -> Decimal:
    """Used-vehicle prices skewed toward 18k-30k with tails to 8k and 45k."""
    # triangular keeps it within bounds and gives a believable shape
    raw = rng.triangular(8000, 45000, 22000)
    return _money(round(raw, 2))


def _random_tradein_value(sale_price: Decimal, rng: random.Random) -> Decimal:
    """25% of customers have a trade-in worth 20-60% of sale price."""
    if rng.random() < 0.25:
        pct = rng.uniform(0.2, 0.6)
        return _money(round(float(sale_price) * pct, 2))
    return Decimal("0.00")


def _inject_tax_collected(
    rng: random.Random,
    txn_id: str,
    sale_price: Decimal,
    trade_in_value: Decimal,
    dealer_state: str,
    ship_to_state: str,
    exempt_flag: bool,
    exempt_cert_id: str | None,
) -> tuple[Decimal, str]:
    """Decide what the POS booked. Returns (tax_collected, error_label).

    error_label is a hidden ground-truth tag used only for evaluating
    the recon engine. It is NOT stored in the production-style table,
    so the recon engine has to rediscover it.
    """
    # Ground truth: what should have been collected.
    truth = compute_tax(
        transaction_id=txn_id,
        sale_price=sale_price,
        trade_in_value=trade_in_value,
        dealer_state=dealer_state,
        ship_to_state=ship_to_state,
        customer_exempt_flag=exempt_flag,
        exempt_cert_id=exempt_cert_id,
    )

    roll = rng.random()
    if roll < 0.08:
        # rate mismatch: wrong rate applied (off by 1 percentage point)
        wrong_rate = truth.rate_applied + Decimal("0.01") * Decimal(rng.choice([-1, 1]))
        wrong_rate = max(wrong_rate, Decimal("0"))
        return _money(truth.taxable_base * wrong_rate), "rate_mismatch"
    if roll < 0.12 and exempt_flag:
        # missing exemption cert: POS still zeroed the tax but cert is blank
        return Decimal("0.00"), "missing_exemption_cert"
    if roll < 0.15 and trade_in_value > 0:
        # trade-in credit error: POS forgot to apply the credit
        return _money(sale_price * truth.rate_applied), "tradein_credit_error"
    if roll < 0.17:
        # sourcing error: POS used the dealer state's rate even when it shouldn't
        dealer_rule = STATE_RULES.get(dealer_state)
        if dealer_rule and dealer_state != truth.taxing_state:
            return _money(truth.taxable_base * dealer_rule["rate"]), "sourcing_error"
    # clean path: POS booked the right amount (with up to 4 cents of rounding noise)
    jitter = Decimal(str(round(rng.uniform(-0.04, 0.04), 2)))
    return _money(truth.tax_owed + jitter), "clean"


def build_dataset() -> tuple[list[dict], list[dict]]:
    """Return (transactions, ground_truth_labels).

    ground_truth_labels is written to a separate table so that during
    real use the recon engine never sees it. Tests use it to score
    recon accuracy.
    """
    rng = random.Random(SEED)
    rows: list[dict] = []
    truth_rows: list[dict] = []

    for i in range(1, TXN_COUNT + 1):
        txn_id = f"T{i:06d}"
        sale_date = _random_date(rng)
        sale_price = _random_sale_price(rng)
        trade_in_value = _random_tradein_value(sale_price, rng)

        # 70% intrastate, 30% interstate sales
        if rng.random() < 0.70:
            dealer_state = ship_to_state = rng.choice(STATES)
        else:
            dealer_state = rng.choice(STATES)
            ship_to_state = rng.choice([s for s in STATES if s != dealer_state])

        ship_to_zip = _random_zip(ship_to_state, rng)

        # 3% exempt
        if rng.random() < 0.03:
            exempt_flag = True
            # half the exempt have a blank cert (induces missing-cert variance)
            exempt_cert_id = f"EX{rng.randint(100000, 999999)}" if rng.random() < 0.5 else None
        else:
            exempt_flag = False
            exempt_cert_id = None

        tax_collected, label = _inject_tax_collected(
            rng=rng,
            txn_id=txn_id,
            sale_price=sale_price,
            trade_in_value=trade_in_value,
            dealer_state=dealer_state,
            ship_to_state=ship_to_state,
            exempt_flag=exempt_flag,
            exempt_cert_id=exempt_cert_id,
        )

        rows.append({
            "transaction_id": txn_id,
            "sale_date": sale_date,
            "sale_price": float(sale_price),
            "trade_in_value": float(trade_in_value),
            "ship_to_state": ship_to_state,
            "ship_to_zip": ship_to_zip,
            "dealer_state": dealer_state,
            "customer_exempt_flag": 1 if exempt_flag else 0,
            "exempt_cert_id": exempt_cert_id,
            "tax_collected": float(tax_collected),
        })
        truth_rows.append({
            "transaction_id": txn_id,
            "ground_truth_label": label,
        })

    return rows, truth_rows


def write_to_sqlite(rows: list[dict], truth_rows: list[dict]) -> Path:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    if DB_PATH.exists():
        DB_PATH.unlink()

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE transactions (
            transaction_id        TEXT PRIMARY KEY,
            sale_date             TEXT NOT NULL,
            sale_price            REAL NOT NULL,
            trade_in_value        REAL NOT NULL,
            ship_to_state         TEXT NOT NULL,
            ship_to_zip           TEXT,
            dealer_state          TEXT NOT NULL,
            customer_exempt_flag  INTEGER NOT NULL DEFAULT 0,
            exempt_cert_id        TEXT,
            tax_collected         REAL NOT NULL
        );
    """)
    cur.execute("""
        CREATE TABLE ground_truth (
            transaction_id        TEXT PRIMARY KEY,
            ground_truth_label    TEXT NOT NULL
        );
    """)
    cur.executemany(
        """
        INSERT INTO transactions
        (transaction_id, sale_date, sale_price, trade_in_value, ship_to_state,
         ship_to_zip, dealer_state, customer_exempt_flag, exempt_cert_id, tax_collected)
        VALUES
        (:transaction_id, :sale_date, :sale_price, :trade_in_value, :ship_to_state,
         :ship_to_zip, :dealer_state, :customer_exempt_flag, :exempt_cert_id, :tax_collected)
        """,
        rows,
    )
    cur.executemany(
        "INSERT INTO ground_truth (transaction_id, ground_truth_label) VALUES (:transaction_id, :ground_truth_label)",
        truth_rows,
    )
    cur.execute("CREATE INDEX idx_txn_state ON transactions(ship_to_state);")
    cur.execute("CREATE INDEX idx_txn_date  ON transactions(sale_date);")
    conn.commit()
    conn.close()
    return DB_PATH


def main() -> Path:
    rows, truth_rows = build_dataset()
    path = write_to_sqlite(rows, truth_rows)
    print(f"Wrote {len(rows):,} transactions to {path}")
    return path


if __name__ == "__main__":
    main()
