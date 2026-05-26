"""tax_engine.py

A Vertex O Series-equivalent tax determination engine for used-vehicle sales.

WHAT THIS DOES (in plain English for a tax reader):
  Given one sale row (price, trade-in value, ship-to state, dealer state,
  exempt flag, cert ID), this module returns the sales/use tax that SHOULD
  have been collected based on the destination state's rules.

WHY IT EXISTS:
  Real retailers use Vertex O Series (or Avalara, Sovos) to compute tax in
  real time during checkout. Vertex looks up the jurisdiction, applies the
  state and local rate, honors trade-in credits where allowed, and honors
  exemption certificates. This file is a small, transparent reproduction
  of that logic. The numbers it produces become the "tax_owed" column the
  GL recon compares against the POS "tax_collected" column.

RATES AND RULES (illustrative, as of 2025):
  - State rates use the state base + an approximate average local component
    to keep the demo tractable. A production Vertex deployment resolves
    every local jurisdiction by ZIP+4. Sources noted next to each row.
  - Trade-in credit treatment is sourced from each state's DOR motor
    vehicle bulletin. Citations are inline.
  - Sourcing rules (origin vs. destination) follow each state's published
    nexus and sourcing guidance.

NOT LEGAL ADVICE. Portfolio demonstration only.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional


# -------------------------------------------------------------
# State rule table
# -------------------------------------------------------------
# Format per state:
#   rate                effective combined rate (state + avg local)
#   sourcing            "destination" or "origin"
#   trade_in_credit     "full", "none", or a numeric cap in dollars
#   notes               source citation
#
# To keep the demo defensible: NC uses a Highway Use Tax (HUT) of 3% for
# motor vehicles in lieu of sales tax. GA uses a one-time Title Ad
# Valorem Tax (TAVT) of 7% in lieu of sales tax. Both are modeled here as
# their effective rate so the engine can treat all 10 states uniformly.
# -------------------------------------------------------------
STATE_RULES = {
    "TX": {
        "rate": Decimal("0.0625"),    # TX motor vehicle SUT is 6.25% flat, no local add-on
        "sourcing": "destination",
        "trade_in_credit": "full",
        "notes": "TX Comptroller Pub 96-254: motor vehicle SUT 6.25% on consideration net of trade-in.",
    },
    "FL": {
        "rate": Decimal("0.07"),      # 6% state + ~1% avg discretionary surtax (cap at first $5k)
        "sourcing": "destination",
        "trade_in_credit": "full",
        "notes": "FL DOR GT-400400: trade-in allowance reduces taxable amount; surtax capped at first $5,000.",
    },
    "CA": {
        "rate": Decimal("0.0875"),    # 7.25% state + ~1.5% avg local
        "sourcing": "destination",
        "trade_in_credit": "none",
        "notes": "CA CDTFA Pub 34: no trade-in credit on vehicle sales between non-dealers; tax applies to full price.",
    },
    "GA": {
        "rate": Decimal("0.07"),      # TAVT 7% one-time title tax in lieu of sales tax
        "sourcing": "destination",
        "trade_in_credit": "full",
        "notes": "GA DOR TAVT-1: Title Ad Valorem Tax 7% of fair market value, trade-in allowance applies.",
    },
    "AZ": {
        "rate": Decimal("0.081"),     # 5.6% TPT + ~2.5% avg city/county
        "sourcing": "origin",
        "trade_in_credit": "full",
        "notes": "AZ DOR TPT Procedure: in-state retail uses origin sourcing; trade-in reduces gross receipts.",
    },
    "NC": {
        "rate": Decimal("0.03"),      # Highway Use Tax 3% in lieu of sales tax
        "sourcing": "destination",
        "trade_in_credit": "full",
        "notes": "NC GS 105-187.3: HUT 3% on retail value net of trade-in.",
    },
    "OH": {
        "rate": Decimal("0.0725"),    # 5.75% state + ~1.5% avg local
        "sourcing": "destination",
        "trade_in_credit": "full",
        "notes": "OH ORC 5739.02: trade-in allowance on like-kind motor vehicle reduces taxable price.",
    },
    "PA": {
        "rate": Decimal("0.06"),      # 6% state; only Allegheny (+1%) and Philly (+2%) add local
        "sourcing": "destination",
        "trade_in_credit": "full",
        "notes": "PA DOR REV-72: trade-in credit allowed; Philadelphia +2%, Allegheny +1% modeled at state base for demo.",
    },
    "IL": {
        "rate": Decimal("0.0725"),    # 6.25% state + ~1% avg local
        "sourcing": "origin",
        "trade_in_credit": Decimal("10000"),  # capped trade-in credit
        "notes": "IL DOR ST-58: first-division motor vehicle trade-in credit capped at $10,000 (PA-101-0031, eff. 1/1/2022 forward).",
    },
    "NY": {
        "rate": Decimal("0.08"),      # 4% state + ~4% avg local
        "sourcing": "destination",
        "trade_in_credit": "full",
        "notes": "NY DTF TB-ST-860: trade-in allowance on motor vehicle reduces receipt subject to tax.",
    },
}


# Tolerance: how many cents of difference between collected and computed
# we forgive before flagging a variance. POS rounding and ZIP+4 drift can
# produce a few cents of jitter even in a clean environment.
ROUNDING_TOLERANCE_USD = Decimal("0.05")


@dataclass
class TaxResult:
    """Output of the engine for one transaction."""
    transaction_id: str
    taxing_state: str
    rate_applied: Decimal
    taxable_base: Decimal
    tax_owed: Decimal
    trade_in_credit_applied: Decimal
    exempt_honored: bool
    sourcing_used: str


def _money(value) -> Decimal:
    """Round to two decimal places, banker-safe."""
    return Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def resolve_taxing_state(dealer_state: str, ship_to_state: str) -> str:
    """Decide which state's rules apply.

    For each potential taxing state we check that state's sourcing rule.
    If the destination state uses origin sourcing AND the dealer is in
    that same state, tax sources to the dealer location. Otherwise we
    follow standard destination sourcing.

    For an out-of-state buyer of a motor vehicle, most states still tax
    at the destination because motor vehicles are titled where they are
    garaged. This demo simplifies to destination sourcing unless both
    dealer and ship_to are in an origin-sourcing state.
    """
    if ship_to_state == dealer_state:
        # Intrastate sale: honor that state's sourcing rule.
        state_rule = STATE_RULES.get(ship_to_state)
        if state_rule and state_rule["sourcing"] == "origin":
            return dealer_state
    # Interstate or destination-sourcing state: tax goes to ship-to.
    return ship_to_state


def compute_tax(
    transaction_id: str,
    sale_price: float | Decimal,
    trade_in_value: float | Decimal,
    dealer_state: str,
    ship_to_state: str,
    customer_exempt_flag: bool,
    exempt_cert_id: Optional[str],
) -> TaxResult:
    """Compute the tax that should have been collected on one sale.

    Steps mirror what Vertex O Series does on a real invoice:
      1. Resolve the taxing jurisdiction (sourcing).
      2. Apply trade-in credit per that state's rule.
      3. Honor any valid exemption certificate.
      4. Apply the combined rate.
      5. Return a structured result for downstream recon.
    """
    sale_price = Decimal(str(sale_price))
    trade_in_value = Decimal(str(trade_in_value))

    taxing_state = resolve_taxing_state(dealer_state, ship_to_state)
    rules = STATE_RULES.get(taxing_state)
    if rules is None:
        # No rule loaded: out of scope. Engine declines to compute.
        return TaxResult(
            transaction_id=transaction_id,
            taxing_state=taxing_state,
            rate_applied=Decimal("0"),
            taxable_base=Decimal("0"),
            tax_owed=Decimal("0"),
            trade_in_credit_applied=Decimal("0"),
            exempt_honored=False,
            sourcing_used="unknown",
        )

    # Step 1: trade-in credit
    credit_rule = rules["trade_in_credit"]
    if credit_rule == "full":
        credit = trade_in_value
    elif credit_rule == "none":
        credit = Decimal("0")
    elif isinstance(credit_rule, Decimal):
        credit = min(trade_in_value, credit_rule)
    else:
        credit = Decimal("0")

    taxable_base = max(sale_price - credit, Decimal("0"))

    # Step 2: exemption. A valid exemption cert ID must be present AND
    # the exempt flag must be set. Empty/null cert is treated as missing
    # cert and the exemption is NOT honored.
    exempt_honored = False
    if customer_exempt_flag and exempt_cert_id and str(exempt_cert_id).strip():
        exempt_honored = True
        tax_owed = Decimal("0")
    else:
        # Step 3: rate
        tax_owed = taxable_base * rules["rate"]

    return TaxResult(
        transaction_id=transaction_id,
        taxing_state=taxing_state,
        rate_applied=rules["rate"],
        taxable_base=_money(taxable_base),
        tax_owed=_money(tax_owed),
        trade_in_credit_applied=_money(credit),
        exempt_honored=exempt_honored,
        sourcing_used=rules["sourcing"],
    )


def supported_states() -> list[str]:
    """Return the list of states the engine has rules for."""
    return sorted(STATE_RULES.keys())
