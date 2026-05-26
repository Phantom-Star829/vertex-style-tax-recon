# vertex-style-tax-recon

A portfolio demonstration of a sales/use tax determination engine and GL reconciliation pipeline for used-vehicle retail, modeled after a Vertex O Series + Oracle Cloud ERP workflow.

The project takes 5,000 synthetic used-vehicle sales transactions, runs them through a small but rule-correct tax engine (10 states, including origin vs. destination sourcing, trade-in credit rules, and exemption certificate handling), reconciles the engine's output against simulated POS-collected tax, categorizes every variance, and produces a returns-ready CSV and a manager-facing PDF. Everything runs locally with one command.

The goal is to make it easy for an indirect tax hiring manager to see, in concrete code, the SQL and Python data-wrangling half of a Staff Accountant role: write the tax content into rules, prove it with tests, build the recon, and ship the deliverable.

---

## Architecture

```
                    +-------------------+
                    | generate_data.py  |
                    | 5,000 synthetic   |
                    | used-vehicle txns |
                    +---------+---------+
                              |
                              v
                    +-------------------+
                    |  SQLite (sales.db)|
                    |  transactions     |
                    |  ground_truth     |
                    +---------+---------+
                              |
              +---------------+---------------+
              |                               |
              v                               v
    +-------------------+           +-------------------+
    |   tax_engine.py   |           |     sql/*.sql     |
    | 10-state rules    |           | analyst showcase  |
    | sourcing, credits |           | window fns, CTEs  |
    | exemption checks  |           +-------------------+
    +---------+---------+
              |
              v
    +-------------------+
    |   reconcile.py    |
    | category logic    |
    | writes recon_     |
    | detail back to db |
    +---------+---------+
              |
              v
    +-------------------+
    | returns_report.py |
    | CSV + PDF outputs |
    +-------------------+
```

---

## How to run

```bash
pip install -r requirements.txt
python -m src.run_all
pytest -q
```

`src/run_all.py` runs the full pipeline end to end. Output lands in `output/`:

- `output/recon_detail.csv` , one row per transaction with variance and category
- `output/recon_summary.csv` , variance aggregated by state and category
- `output/returns_summary.csv` , monthly state-level return-ready rollup
- `output/returns_summary.pdf` , manager-facing one-pager

---

## How this maps to a real Vertex + Oracle Cloud ERP workflow

| This repo | Production analog |
|---|---|
| `src/tax_engine.py` | Vertex O Series tax determination service |
| `STATE_RULES` table | Vertex rate and rule content subscription |
| `data/sales.db` `transactions` table | Vertex tax journal / Oracle AR transaction lines |
| `data/sales.db` `recon_detail` table | Oracle Cloud ERP tax recon staging table |
| `src/reconcile.py` | The monthly recon a Staff Accountant runs in Oracle (or in a workbook fed by Oracle extracts) before returns prep |
| `src/returns_report.py` | The state-by-state return prep extract handed to the return prep team or uploaded to a CRS-style return prep tool |
| `sql/` files | The ad-hoc SQL an analyst writes against Oracle / a finance data warehouse to investigate variances, validate exemptions, and feed returns |

The vocabulary maps cleanly: "rate mismatch," "missing exemption certificate," "sourcing error," and "trade-in credit error" are the same four buckets a real used-vehicle tax recon resolves on a monthly close.

---

## What this demonstrates

- **SQL fluency** , window functions, CTEs, anti-joins, GROUP BY rollups, ROW_NUMBER ranking, rolling-window pattern detection across 8 standalone files
- **Python automation** , dataclasses, Decimal arithmetic for tax math, SQLite I/O, ReportLab PDF generation
- **GL recon mindset** , reconciliation framed around variance categorization and materiality, not just matching
- **Used-vehicle tax content knowledge** , correct trade-in credit treatment per state, HUT and TAVT modeling, origin vs. destination sourcing
- **Vertex vocabulary** , the engine, the journal, the recon, the returns extract; named the same way Vertex docs do
- **Test discipline** , 19 pytest cases pin each rule so the rate table can be revisited without breaking the build

---

## Sample SQL output

`sql/03_missing_exemption_certs.sql`:

```sql
SELECT
    t.transaction_id,
    t.sale_date,
    t.ship_to_state,
    ROUND(t.sale_price, 2)            AS sale_price,
    t.exempt_cert_id,
    ROUND(rd.tax_owed, 2)             AS tax_at_risk
FROM transactions t
LEFT JOIN recon_detail rd USING(transaction_id)
WHERE t.customer_exempt_flag = 1
  AND (t.exempt_cert_id IS NULL OR TRIM(t.exempt_cert_id) = '')
ORDER BY t.sale_price DESC;
```

Each exempt transaction with a missing cert is a state-audit exposure. The query lifts them out of 5,000 rows in seconds.

---

## Disclaimer

Tax rates and rules in this repo are illustrative as of 2025 and simplified for demonstration. They are not legal or tax advice. All transactions are synthetic; no PII or customer data is involved.

## License

MIT. See `LICENSE`.
