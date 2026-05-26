"""Pytest suite for the tax engine.

Each test pins one specific rule. If the rule changes in tax_engine.py,
the test that depends on it will fail loudly, which is exactly the
behavior a tax team wants when revisiting their rate table.
"""

from decimal import Decimal

import pytest

from src.tax_engine import (
    STATE_RULES,
    compute_tax,
    resolve_taxing_state,
    supported_states,
)


# --------- Basic rate application ----------------------------------------

def test_texas_intrastate_basic_rate_with_full_tradein_credit():
    """TX: 6.25%, full trade-in credit, destination."""
    result = compute_tax(
        transaction_id="T001",
        sale_price=20000,
        trade_in_value=5000,
        dealer_state="TX",
        ship_to_state="TX",
        customer_exempt_flag=False,
        exempt_cert_id=None,
    )
    # Taxable base: 20000 - 5000 = 15000. Tax: 15000 * 0.0625 = 937.50
    assert result.taxable_base == Decimal("15000.00")
    assert result.tax_owed == Decimal("937.50")
    assert result.taxing_state == "TX"


def test_california_no_tradein_credit_applies_full_price():
    """CA: 8.75%, NO trade-in credit."""
    result = compute_tax(
        transaction_id="T002",
        sale_price=30000,
        trade_in_value=10000,
        dealer_state="CA",
        ship_to_state="CA",
        customer_exempt_flag=False,
        exempt_cert_id=None,
    )
    # Trade-in ignored. Tax: 30000 * 0.0875 = 2625.00
    assert result.taxable_base == Decimal("30000.00")
    assert result.tax_owed == Decimal("2625.00")
    assert result.trade_in_credit_applied == Decimal("0.00")


def test_illinois_tradein_credit_capped_at_10000():
    """IL: trade-in credit capped at $10,000."""
    result = compute_tax(
        transaction_id="T003",
        sale_price=40000,
        trade_in_value=15000,  # exceeds cap
        dealer_state="IL",
        ship_to_state="IL",
        customer_exempt_flag=False,
        exempt_cert_id=None,
    )
    # Credit clipped to 10,000. Base: 40000 - 10000 = 30000. Tax: 30000 * 0.0725
    assert result.trade_in_credit_applied == Decimal("10000.00")
    assert result.taxable_base == Decimal("30000.00")
    assert result.tax_owed == Decimal("2175.00")


def test_illinois_tradein_below_cap_uses_actual_value():
    result = compute_tax(
        transaction_id="T004",
        sale_price=20000,
        trade_in_value=4000,
        dealer_state="IL",
        ship_to_state="IL",
        customer_exempt_flag=False,
        exempt_cert_id=None,
    )
    assert result.trade_in_credit_applied == Decimal("4000.00")
    assert result.taxable_base == Decimal("16000.00")


# --------- Exemption handling --------------------------------------------

def test_valid_exemption_zeroes_tax():
    result = compute_tax(
        transaction_id="T005",
        sale_price=25000,
        trade_in_value=0,
        dealer_state="TX",
        ship_to_state="TX",
        customer_exempt_flag=True,
        exempt_cert_id="EX123456",
    )
    assert result.tax_owed == Decimal("0.00")
    assert result.exempt_honored is True


def test_exempt_flag_but_blank_cert_does_not_honor():
    result = compute_tax(
        transaction_id="T006",
        sale_price=25000,
        trade_in_value=0,
        dealer_state="TX",
        ship_to_state="TX",
        customer_exempt_flag=True,
        exempt_cert_id="   ",
    )
    assert result.exempt_honored is False
    assert result.tax_owed > Decimal("0")


def test_exempt_flag_but_null_cert_does_not_honor():
    result = compute_tax(
        transaction_id="T007",
        sale_price=15000,
        trade_in_value=0,
        dealer_state="FL",
        ship_to_state="FL",
        customer_exempt_flag=True,
        exempt_cert_id=None,
    )
    assert result.exempt_honored is False
    assert result.tax_owed > Decimal("0")


def test_no_exempt_flag_with_cert_id_is_not_exempt():
    """If the customer didn't claim exempt, having a cert ID on file
    is irrelevant. Tax should still apply.
    """
    result = compute_tax(
        transaction_id="T008",
        sale_price=12000,
        trade_in_value=0,
        dealer_state="NY",
        ship_to_state="NY",
        customer_exempt_flag=False,
        exempt_cert_id="EX999999",
    )
    assert result.exempt_honored is False
    assert result.tax_owed > Decimal("0")


# --------- Sourcing ------------------------------------------------------

def test_destination_sourcing_uses_ship_to_state():
    """TX dealer, FL buyer: tax sources to FL (destination)."""
    state = resolve_taxing_state("TX", "FL")
    assert state == "FL"


def test_origin_sourcing_intrastate_uses_dealer_state():
    """AZ uses origin sourcing for intrastate."""
    state = resolve_taxing_state("AZ", "AZ")
    assert state == "AZ"


def test_interstate_destination_state_origin_rule_does_not_apply():
    """AZ dealer, NY buyer: NY uses destination, tax sources to NY."""
    state = resolve_taxing_state("AZ", "NY")
    assert state == "NY"


def test_illinois_origin_intrastate():
    """IL uses origin sourcing for intrastate sales."""
    state = resolve_taxing_state("IL", "IL")
    assert state == "IL"


# --------- Edge cases ----------------------------------------------------

def test_zero_trade_in_does_not_change_outcome():
    result = compute_tax(
        transaction_id="T010",
        sale_price=10000,
        trade_in_value=0,
        dealer_state="OH",
        ship_to_state="OH",
        customer_exempt_flag=False,
        exempt_cert_id=None,
    )
    # 10000 * 0.0725 = 725.00
    assert result.tax_owed == Decimal("725.00")


def test_trade_in_greater_than_sale_price_clamps_base_to_zero():
    """Pathological case: trade-in worth more than the sale."""
    result = compute_tax(
        transaction_id="T011",
        sale_price=10000,
        trade_in_value=15000,
        dealer_state="TX",
        ship_to_state="TX",
        customer_exempt_flag=False,
        exempt_cert_id=None,
    )
    assert result.taxable_base == Decimal("0.00")
    assert result.tax_owed == Decimal("0.00")


def test_unknown_state_returns_zero_with_unknown_sourcing():
    result = compute_tax(
        transaction_id="T012",
        sale_price=10000,
        trade_in_value=0,
        dealer_state="ZZ",
        ship_to_state="ZZ",
        customer_exempt_flag=False,
        exempt_cert_id=None,
    )
    assert result.tax_owed == Decimal("0.00")
    assert result.sourcing_used == "unknown"


def test_north_carolina_uses_three_percent_hut():
    """NC HUT is 3%, distinct from generic sales tax rates."""
    result = compute_tax(
        transaction_id="T013",
        sale_price=20000,
        trade_in_value=0,
        dealer_state="NC",
        ship_to_state="NC",
        customer_exempt_flag=False,
        exempt_cert_id=None,
    )
    assert result.rate_applied == Decimal("0.03")
    assert result.tax_owed == Decimal("600.00")


def test_supported_states_list_is_complete():
    states = supported_states()
    expected = {"TX", "FL", "CA", "GA", "AZ", "NC", "OH", "PA", "IL", "NY"}
    assert set(states) == expected


def test_florida_full_credit_basic():
    """FL: 7%, full trade-in credit."""
    result = compute_tax(
        transaction_id="T014",
        sale_price=22000,
        trade_in_value=6000,
        dealer_state="FL",
        ship_to_state="FL",
        customer_exempt_flag=False,
        exempt_cert_id=None,
    )
    # 22000 - 6000 = 16000. 16000 * 0.07 = 1120.00
    assert result.taxable_base == Decimal("16000.00")
    assert result.tax_owed == Decimal("1120.00")


def test_all_states_rules_have_required_fields():
    for state, rule in STATE_RULES.items():
        assert "rate" in rule
        assert "sourcing" in rule
        assert "trade_in_credit" in rule
        assert "notes" in rule
        assert rule["sourcing"] in ("destination", "origin"), f"{state} bad sourcing"
