"""Card Optimizer and Liquidity Guard HTTP routes, with the decision model faked."""

import pytest
from fastapi.testclient import TestClient

from app import main
from app.services import card_optimizer, liquidity_guard


@pytest.fixture
def client(monkeypatch):
    async def nimble(state, questions):
        name = next(iter(questions))
        choice = "card_eu_lodged" if name == "card" else "SCA_BYPASS_CORRIDOR"
        return {name: {"type": "choice", "choice": choice, "probabilities": {choice: 1.0}, "confidence": 1.0}}

    async def nimble_lines(state, questions):
        return {i: {"type": "noul", "noul": 0.9 if "on-demand" in q["instructions"].lower() else 0.1}
                for i, q in questions.items()}

    monkeypatch.setattr(card_optimizer, "decide", nimble)
    monkeypatch.setattr(liquidity_guard, "decide", nimble_lines)
    main.RECOMMENDATIONS.clear()
    main.CLASSIFICATIONS.clear()
    return TestClient(main.app)


def test_payments_lists_portfolio_and_analysed_payments(client):
    body = client.get("/api/card-optimizer/payments").json()
    assert len(body["cards"]) == 5 and len(body["payments"]) == 8 and body["recommendations"] == {}
    first = body["payments"][0]
    assert {"transaction", "corridor", "signals", "tags", "current_fee_usd", "options", "rule"} <= set(first)


def test_recommend_stores_the_result(client):
    rec = client.post("/api/card-optimizer/payments/txn_xb_01/recommend").json()
    assert rec["reason_code"] == "SCA_BYPASS_CORRIDOR" and rec["route"] == "/v1/systemone"
    assert client.get("/api/card-optimizer/payments").json()["recommendations"]["txn_xb_01"] == rec


def test_reset_clears_every_recommendation(client):
    client.post("/api/card-optimizer/payments/txn_xb_01/recommend")
    client.post("/api/card-optimizer/payments/txn_xb_02/recommend")
    assert client.delete("/api/card-optimizer/recommendations").json() == {"cleared": 2}
    assert client.get("/api/card-optimizer/payments").json()["recommendations"] == {}


def test_unknown_payment_is_404(client):
    assert client.post("/api/card-optimizer/payments/nope/recommend").status_code == 404


def test_unknown_module_route_is_404_not_locked(client):
    assert client.get("/api/liquidity-guard/anything").status_code == 404


def test_modules_list_liquidity_guard_as_live(client):
    mods = {m["id"]: m for m in client.get("/api/modules").json()}
    assert mods["liquidity-guard"]["locked"] is False


def test_bills_start_unclassified(client):
    body = client.get("/api/liquidity-guard/bills").json()
    assert body["classifications"] == {} and len(body["forecast"]["bills"]) == 9
    assert body["forecast"]["totals"]["unclassified_bills"] == 9


def test_classify_stores_the_result_and_updates_the_forecast(client):
    body = client.post("/api/liquidity-guard/bills/bill_aws/classify").json()
    c = body["classification"]
    assert c["route"] == "/v1/systemone" and c["lines"]["aws_ec2"]["variable"] is True
    assert c["lines"]["aws_savings_plan"]["variable"] is False
    aws = next(b for b in body["forecast"]["bills"] if b["id"] == "bill_aws")
    assert aws["classified"] and body["forecast"]["totals"]["unclassified_bills"] == 8
    assert client.get("/api/liquidity-guard/bills").json()["classifications"]["bill_aws"] == c


def test_reset_clears_every_classification(client):
    client.post("/api/liquidity-guard/bills/bill_aws/classify")
    client.post("/api/liquidity-guard/bills/bill_gcp/classify")
    assert client.delete("/api/liquidity-guard/classifications").json() == {"cleared": 2}
    assert client.get("/api/liquidity-guard/bills").json()["classifications"] == {}


def test_unknown_bill_is_404(client):
    assert client.post("/api/liquidity-guard/bills/nope/classify").status_code == 404
