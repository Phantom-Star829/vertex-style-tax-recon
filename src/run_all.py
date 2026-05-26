"""run_all.py: end-to-end pipeline.

Usage:
    python -m src.run_all

Steps:
    1. Generate synthetic transactions and load to SQLite.
    2. Run the tax engine against every transaction.
    3. Reconcile engine output vs. POS, categorize variances.
    4. Build the returns-ready CSV and PDF.
"""

from __future__ import annotations

from . import generate_data, reconcile, returns_report


def main() -> None:
    print("[1/3] Generating synthetic dataset...")
    generate_data.main()
    print("[2/3] Reconciling tax_collected vs tax_owed...")
    reconcile.run()
    print("[3/3] Building returns-ready CSV + PDF...")
    returns_report.run()
    print("Done.")


if __name__ == "__main__":
    main()
