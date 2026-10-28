"""card_optimizer: what is sent to nimble, the two-step decision, and how its answer is used."""

import asyncio

import pytest

from app.services import card_optimizer
from app.services.corridor import NO_CHANGE, REASON_CODES, get_analysis
from app.services.ollama_client import OllamaUnavailable


class FakeNimble:
    """Records every decide() call and answers from a script: {question name: choice}."""

    def __init__(self, card, reason=None):
        self.card, self.reason, self.calls = card, reason, []

    async def __call__(self, state, questions):
        self.calls.append({"state": state, "questions": questions})
        name = next(iter(questions))
        choice = self.card if name == "card" else self.reason
        probs = {k: (0.9 if k == choice else 0.1 / (len(questions[name]["criteria"]) - 1))
                 for k in questions[name]["criteria"]}
        return {name: {"type": "choice", "choice": choice, "probabilities": probs, "confidence": 0.8}}


def run(analysis):
    return asyncio.run(card_optimizer.recommend(analysis))


# ---------------------------------------------------------------- what nimble is asked

def test_card_question_offers_every_card_described_by_facts_only():
    q = card_optimizer._card_question(get_analysis("txn_xb_06"))["card"]
    assert q["type"] == "choice" and 2 <= len(q["criteria"]) <= 26
    assert set(q["criteria"]) == {"card_us_visa", "card_us_mc", "card_eu_lodged", "card_uk_visa", "card_sg_multi"}
    uk = q["criteria"]["card_uk_visa"]
    assert "holds GBP" in uk and "corporate SCA exemption: yes" in uk and "= 0.00 USD" in uk
    text = " ".join(q["criteria"].values()).lower()
    for hint in ("best", "eligible", "recommended", "can't work", "can work"):
        assert hint not in text, f"card options must not hint at the answer ({hint!r})"


def test_state_is_the_raw_payment_without_the_rule_answer():
    state = card_optimizer._state(get_analysis("txn_xb_01"))
    assert state["payment"]["decline_code"] == "1A"
    assert state["current_card_fees"] == "3.00% FX + 1.00% cross-border = 99.81 USD"
    assert "rule" not in state and "signals" not in state


def test_reason_question_offers_the_three_codes_and_no_change():
    q = card_optimizer._reason_question()["reason_code"]
    assert q["type"] == "choice" and list(q["criteria"]) == [*REASON_CODES, NO_CHANGE]


# ---------------------------------------------------------------- two-step decision

def test_two_calls_pick_the_card_then_classify_the_switch(monkeypatch):
    nimble = FakeNimble("card_uk_visa", "FX_INTERBANK_MATCH")
    monkeypatch.setattr(card_optimizer, "decide", nimble)
    rec = run(get_analysis("txn_xb_06"))  # Bloomberg, GBP on a US card

    assert [list(c["questions"]) for c in nimble.calls] == [["card"], ["reason_code"]]
    assert "proposed_switch" not in nimble.calls[0]["state"]
    switch = nimble.calls[1]["state"]["proposed_switch"]
    assert switch["fx_fee"] == "3.00% -> 0.00%" and switch["fx_fee_saving_usd"] == 184.78
    assert switch["cross_border_fee"] == "1.00% -> 0.00%" and switch["cross_border_fee_saving_usd"] == 61.59
    assert switch["total_saving_usd"] == 246.38
    assert switch["from"].startswith("Visa Corporate ****4471 (current card)")
    assert switch["to"].startswith("Visa Commercial (UK) ****5562")

    assert (rec["reason_code"], rec["recommended_card_id"]) == ("FX_INTERBANK_MATCH", "card_uk_visa")
    assert (rec["source"], rec["model"], rec["route"]) == ("decision model", "nimble", "/v1/systemone")
    assert rec["probabilities"]["FX_INTERBANK_MATCH"] == 0.9
    assert rec["card_probabilities"]["card_uk_visa"] == 0.9
    assert rec["agrees_with_rules"] and rec["fees_saved_usd"] == 246.38


def test_keeping_the_current_card_is_no_change_with_one_call(monkeypatch):
    nimble = FakeNimble("card_us_visa")
    monkeypatch.setattr(card_optimizer, "decide", nimble)
    rec = run(get_analysis("txn_xb_08"))  # Shopify, small FX fee
    assert len(nimble.calls) == 1
    assert rec["reason_code"] == NO_CHANGE and rec["agrees_with_rules"]
    assert rec["fees_saved_usd"] == 0.0 and rec["action"] == "Keep the current card."


def test_failed_payment_recovers_the_amount(monkeypatch):
    monkeypatch.setattr(card_optimizer, "decide", FakeNimble("card_eu_lodged", "SCA_BYPASS_CORRIDOR"))
    rec = run(get_analysis("txn_xb_01"))  # OVH, declined 1A
    assert rec["recovered_usd"] == 2495.23 and rec["fees_saved_usd"] == 99.81
    assert rec["action"].startswith("Retry on Mastercard Lodged Virtual (IE)")
    assert "1A" in rec["rationale"]


# ---------------------------------------------------------------- nimble's answer is never overwritten

def test_disagreement_with_the_rules_is_shown_not_corrected(monkeypatch):
    monkeypatch.setattr(card_optimizer, "decide", FakeNimble("card_sg_multi", NO_CHANGE))
    rec = run(get_analysis("txn_xb_05"))  # rules say FX_INTERBANK_MATCH
    assert rec["reason_code"] == NO_CHANGE
    assert not rec["agrees_with_rules"] and rec["rule"]["reason_code"] == "FX_INTERBANK_MATCH"
    assert rec["warnings"] == []


def test_a_card_the_rules_think_cannot_work_is_flagged_and_recovers_nothing(monkeypatch):
    monkeypatch.setattr(card_optimizer, "decide", FakeNimble("card_us_mc", "SCA_BYPASS_CORRIDOR"))
    rec = run(get_analysis("txn_xb_01"))
    assert rec["recommended_card_id"] == "card_us_mc"
    assert rec["recovered_usd"] == 0.0 and "same SCA challenge" in rec["warnings"][0]


# ---------------------------------------------------------------- fallbacks

async def _unavailable(*args, **kwargs):
    raise OllamaUnavailable("Ollama doesn't serve /v1/systemone; the decision API needs Ollama 0.35 or newer")


def test_falls_back_to_gemma3_structured_outputs(monkeypatch):
    async def gemma(system, prompt, schema):
        assert schema["properties"]["reason_code"]["enum"] == [*REASON_CODES, NO_CHANGE]
        assert "card_uk_visa:" in prompt
        return {"reason_code": "FX_INTERBANK_MATCH", "recommended_card_id": "card_uk_visa", "confidence": 0.7}

    monkeypatch.setattr(card_optimizer, "decide", _unavailable)
    monkeypatch.setattr(card_optimizer, "structured_chat", gemma)
    rec = run(get_analysis("txn_xb_06"))
    assert (rec["source"], rec["route"]) == ("language model", "/api/chat")
    assert "0.35" in rec["notes"][0] and rec["agrees_with_rules"]


def test_falls_back_to_the_rules_when_no_model_is_available(monkeypatch):
    monkeypatch.setattr(card_optimizer, "decide", _unavailable)
    monkeypatch.setattr(card_optimizer, "structured_chat", _unavailable)
    rec = run(get_analysis("txn_xb_04"))
    assert rec["source"] == "rules (models unavailable)" and rec["route"] is None
    assert (rec["reason_code"], rec["recommended_card_id"]) == ("INTER-REGIONAL_ROUTING", "card_sg_multi")
    assert len(rec["notes"]) == 2


@pytest.mark.parametrize("txn_id", [f"txn_xb_0{i}" for i in range(1, 9)])
def test_every_payment_produces_a_complete_recommendation(monkeypatch, txn_id):
    monkeypatch.setattr(card_optimizer, "decide", _unavailable)
    monkeypatch.setattr(card_optimizer, "structured_chat", _unavailable)
    rec = run(get_analysis(txn_id))
    for key in ("reason_code", "action", "rationale", "fees_saved_usd", "recovered_usd", "rule", "warnings"):
        assert key in rec
    assert rec["action"] and rec["rationale"]
