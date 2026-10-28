"""Corridor engine: normalisation, fees, friction, eligibility, the rule answer and savings."""

import pytest

from app.services.corridor import (CARDS, NO_CHANGE, card_cost, friction, get_analysis, normalise,
                                   savings)


def test_normalise_cleans_messy_feed():
    txn = normalise({"merchant_country": "DEU", "currency": "eur", "amount": "76,500", "status": "SETTLED"})
    assert txn["merchant_country"] == "DE"
    assert txn["currency"] == "EUR"
    assert txn["amount"] == 76500.0
    assert txn["amount_usd"] == round(76500 * 1.08, 2)


def test_card_cost_drops_fx_when_card_holds_currency_and_cross_border_in_same_region():
    txn = {"currency": "GBP", "merchant_country": "GB", "amount_usd": 1000.0}
    assert card_cost(txn, CARDS["card_uk_visa"]) == {"fx_bps": 0, "cross_border_bps": 0, "total_bps": 0,
                                                      "fee_usd": 0.0, "inter_regional": False}
    us = card_cost(txn, CARDS["card_us_visa"])
    assert (us["fx_bps"], us["cross_border_bps"], us["fee_usd"]) == (300, 100, 40.0)


@pytest.mark.parametrize("code, text, sca, block", [
    ("1A", "SCA_REQUIRED / soft decline", True, False),
    ("65", "Soft decline (65)", True, False),
    (None, "3DS2 challenge pending", True, False),
    ("05", "do not honor - cross-region MCC block", False, True),
])
def test_friction_reads_decline_codes_and_text(code, text, sca, block):
    f = friction({"decline_code": code, "decline_text": text, "status": "DECLINED"})
    assert (f["sca_challenge"], f["regional_block"], f["failed"]) == (sca, block, True)


def test_settled_payment_has_no_friction():
    assert friction({"decline_code": None, "decline_text": None, "status": "SETTLED"}) == {
        "sca_challenge": False, "regional_block": False, "failed": False}


def test_eligibility_explains_why_a_card_cannot_work():
    options = {o["card_id"]: o for o in get_analysis("txn_xb_01")["options"]}  # OVH, declined 1A on US Visa
    assert "this card already failed" in options["card_us_visa"]["issues"]
    assert options["card_us_mc"]["issues"] == ["would face the same SCA challenge"]
    assert options["card_eu_lodged"]["eligible"]


@pytest.mark.parametrize("txn_id, code, card", [
    ("txn_xb_01", "SCA_BYPASS_CORRIDOR", "card_eu_lodged"),
    ("txn_xb_02", "SCA_BYPASS_CORRIDOR", "card_eu_lodged"),
    ("txn_xb_03", "INTER-REGIONAL_ROUTING", "card_sg_multi"),
    ("txn_xb_04", "INTER-REGIONAL_ROUTING", "card_sg_multi"),
    ("txn_xb_05", "FX_INTERBANK_MATCH", "card_sg_multi"),
    ("txn_xb_06", "FX_INTERBANK_MATCH", "card_uk_visa"),
    ("txn_xb_07", "SCA_BYPASS_CORRIDOR", "card_eu_lodged"),
    ("txn_xb_08", NO_CHANGE, "card_us_visa"),
])
def test_rule_answer_for_every_mock_payment(txn_id, code, card):
    rule = get_analysis(txn_id)["rule"]
    assert (rule["reason_code"], rule["card_id"]) == (code, card)


def test_savings_recover_a_failed_payment_only_on_a_working_card():
    a = get_analysis("txn_xb_01")
    assert savings(a, "card_eu_lodged") == {"fees_saved_usd": 99.81, "recovered_usd": 2495.23}
    assert savings(a, "card_us_mc")["recovered_usd"] == 0.0
    assert savings(a, None) == {"fees_saved_usd": 0.0, "recovered_usd": 0.0}


def test_savings_on_a_settled_payment_are_fees_only():
    assert savings(get_analysis("txn_xb_06"), "card_uk_visa") == {"fees_saved_usd": 246.38, "recovered_usd": 0.0}
