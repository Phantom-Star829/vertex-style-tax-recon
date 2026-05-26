"""returns_report.py

Build the monthly returns-ready summary that a tax analyst would hand
to the manager or upload to a CRS-style return prep tool.

OUTPUTS:
  output/returns_summary.csv       analyst-facing tabular file
  output/returns_summary.pdf       manager-facing one-pager (ReportLab)

LAYOUT NOTES (PDF):
  - Centered headers
  - Clean table grid
  - Dark accent color in a Carvana-style minimalist palette
"""

from __future__ import annotations

import csv
import sqlite3
from datetime import datetime
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak,
)
from reportlab.lib.enums import TA_CENTER, TA_LEFT

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "sales.db"
OUTPUT_DIR = Path(__file__).resolve().parent.parent / "output"
CSV_PATH = OUTPUT_DIR / "returns_summary.csv"
PDF_PATH = OUTPUT_DIR / "returns_summary.pdf"

# Carvana-leaning minimalist palette
ACCENT_DARK = colors.HexColor("#0F2A44")
ACCENT_LIGHT = colors.HexColor("#E5EEF6")
TEXT_GREY = colors.HexColor("#3F4A55")


def _query_monthly_rollup(conn: sqlite3.Connection) -> list[dict]:
    """One row per (state, year-month) with the return-ready totals."""
    sql = """
        SELECT  t.ship_to_state                                   AS state,
                substr(t.sale_date, 1, 7)                         AS period,
                COUNT(*)                                          AS txn_count,
                ROUND(SUM(t.sale_price), 2)                       AS gross_sales,
                ROUND(SUM(CASE WHEN t.customer_exempt_flag = 1
                               THEN t.sale_price ELSE 0 END), 2)  AS exempt_sales,
                ROUND(SUM(CASE WHEN t.customer_exempt_flag = 0
                               THEN t.sale_price ELSE 0 END), 2)  AS taxable_sales,
                ROUND(SUM(rd.tax_owed), 2)                        AS tax_owed,
                ROUND(SUM(rd.tax_collected), 2)                   AS tax_collected,
                ROUND(SUM(rd.variance), 2)                        AS variance
        FROM    transactions t
        JOIN    recon_detail rd USING(transaction_id)
        GROUP BY t.ship_to_state, period
        ORDER BY t.ship_to_state, period;
    """
    return [dict(r) for r in conn.execute(sql).fetchall()]


def _query_state_totals(conn: sqlite3.Connection) -> list[dict]:
    """Annualized state totals for the manager-facing summary page."""
    sql = """
        SELECT  t.ship_to_state                                   AS state,
                COUNT(*)                                          AS txn_count,
                ROUND(SUM(t.sale_price), 2)                       AS gross_sales,
                ROUND(SUM(CASE WHEN t.customer_exempt_flag = 1
                               THEN t.sale_price ELSE 0 END), 2)  AS exempt_sales,
                ROUND(SUM(CASE WHEN t.customer_exempt_flag = 0
                               THEN t.sale_price ELSE 0 END), 2)  AS taxable_sales,
                ROUND(SUM(rd.tax_owed), 2)                        AS tax_owed,
                ROUND(SUM(rd.tax_collected), 2)                   AS tax_collected,
                ROUND(SUM(rd.variance), 2)                        AS variance
        FROM    transactions t
        JOIN    recon_detail rd USING(transaction_id)
        GROUP BY t.ship_to_state
        ORDER BY t.ship_to_state;
    """
    return [dict(r) for r in conn.execute(sql).fetchall()]


def _query_category_totals(conn: sqlite3.Connection) -> list[dict]:
    sql = """
        SELECT  category,
                COUNT(*)                       AS txn_count,
                ROUND(SUM(variance), 2)        AS total_variance
        FROM    recon_detail
        GROUP BY category
        ORDER BY ABS(SUM(variance)) DESC;
    """
    return [dict(r) for r in conn.execute(sql).fetchall()]


def _fmt_money(value) -> str:
    if value is None:
        return ""
    return f"${value:,.2f}"


def _build_pdf(monthly: list[dict], state_totals: list[dict], category_totals: list[dict]) -> None:
    PDF_PATH.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(PDF_PATH),
        pagesize=LETTER,
        leftMargin=0.6 * inch,
        rightMargin=0.6 * inch,
        topMargin=0.6 * inch,
        bottomMargin=0.6 * inch,
        title="Sales/Use Tax Returns Summary",
        author="Nick Gardner",
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "TitleCenter",
        parent=styles["Title"],
        alignment=TA_CENTER,
        textColor=ACCENT_DARK,
        spaceAfter=4,
    )
    subtitle_style = ParagraphStyle(
        "SubtitleCenter",
        parent=styles["Normal"],
        alignment=TA_CENTER,
        textColor=TEXT_GREY,
        fontSize=10,
        spaceAfter=18,
    )
    section_style = ParagraphStyle(
        "Section",
        parent=styles["Heading2"],
        alignment=TA_LEFT,
        textColor=ACCENT_DARK,
        spaceBefore=14,
        spaceAfter=8,
    )
    note_style = ParagraphStyle(
        "Note",
        parent=styles["Italic"],
        alignment=TA_LEFT,
        textColor=TEXT_GREY,
        fontSize=8,
        spaceBefore=10,
    )

    story = []
    story.append(Paragraph("Sales/Use Tax Returns Summary", title_style))
    story.append(Paragraph(
        f"Synthetic used-vehicle dataset, period 2025. Generated {datetime.now().strftime('%B %d, %Y')}.",
        subtitle_style,
    ))

    # State totals table
    story.append(Paragraph("State Totals", section_style))
    state_header = ["State", "Txn Count", "Gross Sales", "Exempt", "Taxable", "Tax Owed", "Tax Collected", "Variance"]
    state_rows = [state_header]
    for r in state_totals:
        state_rows.append([
            r["state"],
            f"{r['txn_count']:,}",
            _fmt_money(r["gross_sales"]),
            _fmt_money(r["exempt_sales"]),
            _fmt_money(r["taxable_sales"]),
            _fmt_money(r["tax_owed"]),
            _fmt_money(r["tax_collected"]),
            _fmt_money(r["variance"]),
        ])
    state_table = Table(state_rows, repeatRows=1, hAlign="CENTER")
    state_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), ACCENT_DARK),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
        ("ALIGN", (0, 0), (0, -1), "CENTER"),
        ("ALIGN", (0, 0), (-1, 0), "CENTER"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, ACCENT_LIGHT]),
        ("GRID", (0, 0), (-1, -1), 0.25, TEXT_GREY),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(state_table)

    # Category totals
    story.append(Paragraph("Variance by Category", section_style))
    cat_rows = [["Category", "Txn Count", "Total Variance"]]
    for r in category_totals:
        cat_rows.append([
            r["category"].replace("_", " ").title(),
            f"{r['txn_count']:,}",
            _fmt_money(r["total_variance"]),
        ])
    cat_table = Table(cat_rows, repeatRows=1, hAlign="CENTER", colWidths=[2.6 * inch, 1.3 * inch, 1.5 * inch])
    cat_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), ACCENT_DARK),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
        ("ALIGN", (0, 0), (-1, 0), "CENTER"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, ACCENT_LIGHT]),
        ("GRID", (0, 0), (-1, -1), 0.25, TEXT_GREY),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(cat_table)

    story.append(PageBreak())

    # Monthly detail by state
    story.append(Paragraph("Monthly Detail by State", section_style))
    monthly_header = ["State", "Period", "Txns", "Gross Sales", "Taxable", "Tax Owed", "Tax Collected", "Variance"]
    monthly_rows = [monthly_header]
    for r in monthly:
        monthly_rows.append([
            r["state"], r["period"], f"{r['txn_count']:,}",
            _fmt_money(r["gross_sales"]),
            _fmt_money(r["taxable_sales"]),
            _fmt_money(r["tax_owed"]),
            _fmt_money(r["tax_collected"]),
            _fmt_money(r["variance"]),
        ])
    monthly_table = Table(monthly_rows, repeatRows=1, hAlign="CENTER")
    monthly_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), ACCENT_DARK),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 7.5),
        ("ALIGN", (2, 1), (-1, -1), "RIGHT"),
        ("ALIGN", (0, 0), (-1, 0), "CENTER"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, ACCENT_LIGHT]),
        ("GRID", (0, 0), (-1, -1), 0.25, TEXT_GREY),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    story.append(monthly_table)

    story.append(Paragraph(
        "Source: synthetic dataset. Rates are illustrative as of 2025. Not legal advice.",
        note_style,
    ))

    doc.build(story)


def run() -> tuple[Path, Path]:
    if not DB_PATH.exists():
        raise FileNotFoundError(f"{DB_PATH} not found. Run generate_data and reconcile first.")

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    monthly = _query_monthly_rollup(conn)
    state_totals = _query_state_totals(conn)
    category_totals = _query_category_totals(conn)
    conn.close()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # CSV
    with CSV_PATH.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(monthly[0].keys()))
        writer.writeheader()
        writer.writerows(monthly)

    _build_pdf(monthly, state_totals, category_totals)

    print(f"Wrote {CSV_PATH}")
    print(f"Wrote {PDF_PATH}")
    return CSV_PATH, PDF_PATH


if __name__ == "__main__":
    run()
