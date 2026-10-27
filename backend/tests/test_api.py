"""Card Optimizer HTTP routes, with the decision model faked."""

import pytest
from fastapi.testclient import TestClient

from app import main
from app.services import card_optimizer


@pytest.fixture
def client(monkeypatch):
    async def nimble(state, questions):
        name = next(iter(questions))
        choice = "card_eu_lodged" if name == "card" else "SCA_BYPASS_CORRIDOR"
        return {name: {"type": "choice", "choice": choice, "probabilities": {choice: 1.0}, "confidence": 1.0}}

    monkeypatch.setattr(card_optimizer, "decide", nimble)
    main.RECOMMENDATIONS.clear()
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


def test_unknown_payment_is_404(client):
    assert client.post("/api/card-optimizer/payments/nope/recommend").status_code == 404


def test_liquidity_guard_is_still_locked(client):
    assert client.get("/api/liquidity-guard/anything").status_code == 423
