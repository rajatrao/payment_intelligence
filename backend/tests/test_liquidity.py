"""Liquidity Guard: the line rule, the forecast engine, what is sent to nimble, and how its answer is used."""

import asyncio

from app.services import liquidity, liquidity_guard
from app.services.ollama_client import OllamaUnavailable

VARIABLE_LINES = {"aws_ec2", "aws_transfer", "aws_bedrock", "aws_support", "gcp_bigquery", "gcp_gke", "gcp_storage",
                  "meta_launch", "meta_retarget", "sf_compute", "sf_storage", "tw_sms", "dd_ondemand", "dd_logs"}
FIXED_LINES = {"aws_savings_plan", "gcp_cud", "sf_capacity", "tw_numbers", "dd_hosts", "slack_seats",
               "sfdc_licenses", "office_desks"}


def all_lines():
    return {l["id"]: l for b in liquidity.bills() for l in b["lines"]}


def rules():
    return {i: l["rule"]["variable"] for i, l in all_lines().items()}


class FakeNimble:
    """Records every decide() call and answers each noul question from a script: {line id: probability}."""

    def __init__(self, probs):
        self.probs, self.calls = probs, []

    async def __call__(self, state, questions):
        self.calls.append({"state": state, "questions": questions})
        return {i: {"type": "noul", "noul": self.probs[i]} for i in questions if i in self.probs}


# ---------------------------------------------------------------- rule engine and data

def test_rule_classifies_every_line_as_intended():
    assert set(all_lines()) == VARIABLE_LINES | FIXED_LINES
    r = rules()
    assert {i for i, v in r.items() if v} == VARIABLE_LINES
    assert {i for i, v in r.items() if not v} == FIXED_LINES


def test_strong_usage_markers_beat_commitment_wording():
    assert all_lines()["dd_ondemand"]["rule"]["variable"] is True   # "on-demand hosts above commitment"
    assert all_lines()["dd_hosts"]["rule"]["variable"] is False     # "150 committed hosts"


def test_messy_amounts_are_parsed():
    lines = all_lines()
    assert lines["aws_ec2"]["mtd"] == 21880.40 and lines["aws_ec2"]["avg3"] == 9590.0


# ---------------------------------------------------------------- forecast

def test_variable_lines_are_run_rated_and_fixed_lines_are_not():
    line = all_lines()["aws_ec2"]
    assert liquidity.project(line, True) == round(21880.40 * 31 / 27, 2)
    assert liquidity.project(line, False) == 21880.40
    assert liquidity.project(line, None) == 21880.40


def test_unclassified_forecast_looks_safe():
    t = liquidity.forecast({})["totals"]
    assert t["unclassified_bills"] == 9 and t["variable_exposure"] == 0
    assert t["low_point"] == {"balance": 81791.70, "date": "2026-11-03"} and t["first_breach"] is None


def test_classified_forecast_reveals_the_buffer_breach():
    f = liquidity.forecast(rules())
    t = f["totals"]
    assert t["unclassified_bills"] == 0
    assert t["debits"] == 164359.09 and t["variable_exposure"] == 132221.09 and t["surprise"] == 69868.75
    assert t["low_point"] == {"balance": 65880.54, "date": "2026-11-03"} and t["first_breach"] == "2026-11-03"
    meta = next(b for b in f["bills"] if b["id"] == "bill_meta")
    assert meta["spike"] and meta["variable_lines"] == 2


def test_timeline_is_in_date_order_with_outflows_first_on_each_day():
    events = liquidity.forecast(rules())["timeline"]
    keys = [(e["date"], e["amount"] > 0) for e in events]
    assert keys == sorted(keys)
    balance = liquidity.forecast({})["account"]["balance"]
    for e in events:
        balance = round(balance + e["amount"], 2)
        assert e["balance_after"] == balance and e["below_buffer"] == (balance < 75000)


def test_unclassified_bills_are_marked_as_estimates():
    events = liquidity.forecast({"slack_seats": False})["timeline"]
    bills = {e["bill_id"]: e for e in events if e["kind"] == "bill"}
    assert bills["bill_slack"]["estimate"] is False and bills["bill_aws"]["estimate"] is True


# ---------------------------------------------------------------- what nimble is asked

def test_one_noul_question_per_line_with_no_answer_hints(monkeypatch):
    bill = liquidity.get_bill("bill_aws")
    nimble = FakeNimble({i: 0.9 for i in all_lines()})
    monkeypatch.setattr(liquidity_guard, "decide", nimble)
    asyncio.run(liquidity_guard.classify(bill))
    call = nimble.calls[0]
    assert set(call["questions"]) == {l["id"] for l in bill["lines"]}
    for q in call["questions"].values():
        assert q["type"] == "noul" and q["instructions"].endswith("Is this a variable usage-based consumption line?")
        assert "after 27 of 31 days" in q["instructions"]
    assert set(call["state"]) == {"vendor", "descriptor", "auto_debit_date", "definition"}
    sent = str(call).lower()
    for hint in ("rule", "variable\": true", "metered usage\"", "why"):
        assert hint not in sent, f"nimble must not see the rule answer ({hint!r})"


# ---------------------------------------------------------------- how the answer is used

def test_probability_threshold_is_one_half(monkeypatch):
    bill = liquidity.get_bill("bill_datadog")
    monkeypatch.setattr(liquidity_guard, "decide", FakeNimble({"dd_hosts": 0.49, "dd_ondemand": 0.5, "dd_logs": 0.97}))
    out = asyncio.run(liquidity_guard.classify(bill))
    assert out["source"] == "decision model" and out["route"] == "/v1/systemone"
    assert {i: l["variable"] for i, l in out["lines"].items()} == {"dd_hosts": False, "dd_ondemand": True,
                                                                   "dd_logs": True}
    assert out["lines"]["dd_logs"]["probability"] == 0.97 and out["agreements"] == 3


def test_disagreement_is_shown_not_overwritten(monkeypatch):
    bill = liquidity.get_bill("bill_slack")
    monkeypatch.setattr(liquidity_guard, "decide", FakeNimble({"slack_seats": 0.8}))
    line = asyncio.run(liquidity_guard.classify(bill))["lines"]["slack_seats"]
    assert line["variable"] is True and line["rule"]["variable"] is False and line["agrees_with_rules"] is False


def test_missing_line_falls_back_to_gemma3(monkeypatch):
    bill = liquidity.get_bill("bill_twilio")
    monkeypatch.setattr(liquidity_guard, "decide", FakeNimble({"tw_sms": 0.9}))

    async def gemma(system, prompt, schema):
        assert schema["required"] == ["tw_sms", "tw_numbers"]
        return {"tw_sms": True, "tw_numbers": False}

    monkeypatch.setattr(liquidity_guard, "structured_chat", gemma)
    out = asyncio.run(liquidity_guard.classify(bill))
    assert out["source"] == "language model" and out["route"] == "/api/chat"
    assert "no probability for some lines" in out["notes"][0]
    assert out["lines"]["tw_sms"]["probability"] is None and out["lines"]["tw_sms"]["variable"] is True


def test_no_models_falls_back_to_rules(monkeypatch):
    async def down(*a, **k):
        raise OllamaUnavailable("unreachable")

    monkeypatch.setattr(liquidity_guard, "decide", down)
    monkeypatch.setattr(liquidity_guard, "structured_chat", down)
    out = asyncio.run(liquidity_guard.classify(liquidity.get_bill("bill_gcp")))
    assert out["source"] == "rules (models unavailable)" and out["route"] is None and len(out["notes"]) == 2
    assert out["agreements"] == 4


def test_flat_merges_every_bill():
    c = {"a": {"lines": {"x": {"variable": True}}}, "b": {"lines": {"y": {"variable": False}}}}
    assert liquidity_guard.flat(c) == {"x": True, "y": False}
