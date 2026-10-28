"""Strategic Horizon: the ledgers and calendars, what is sent to Timestral, the fallback, breach, sweep and routes."""

import asyncio
import dataclasses
import time
from datetime import date

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app import main
from app.data.transactions import ledger
from app.data.transactions.recurring import ACCOUNTS, RECURRING_BILLS
from app.services import horizon

OPS, CARDS, MKT = "acct_operating", "acct_cards", "acct_marketing"


class FakeForecast:
    def __init__(self, q):
        self.q = q

    def quantile(self, p):
        return self.q[p]


class FakeTimestral:
    """Records the call and returns a straight-line corridor around each series' last balance."""

    def __init__(self, delay=0.0):
        self.calls, self.delay = [], delay

    def forecast(self, context, prediction_length, known_covariates):
        time.sleep(self.delay)
        self.calls.append({"context": context, "prediction_length": prediction_length, "known": known_covariates})
        base = context[:, :, -1:]
        q = {p: np.repeat(base + off, prediction_length, axis=2) for p, off in ((0.1, -10000), (0.5, 0), (0.9, 10000))}
        return FakeForecast(q)


def use_model(monkeypatch, model):
    monkeypatch.setattr(horizon, "load_model", lambda: model)


def no_model(monkeypatch, why="the timestral package is not installed"):
    def fail():
        raise horizon.ForecastUnavailable(why)
    monkeypatch.setattr(horizon, "load_model", fail)


def fallback_raw():
    return {"quantiles": {a: horizon.statistical_forecast(a) for a in ledger.ACCOUNT_IDS},
            "source": "statistical fallback", "model": "x", "route": None, "notes": []}


# ---------------------------------------------------------------- ledger and calendar

def test_the_same_three_accounts_as_the_tactical_view():
    assert ledger.ACCOUNT_IDS == [a["id"] for a in ACCOUNTS]
    for a in ACCOUNTS:
        acct = ledger.account(a["id"])
        assert acct["name"] == a["name"] and acct["floor"] == a["minimum_buffer"]
        assert acct["balance"] == float(a["balance"].replace(",", ""))


def test_history_is_180_repeatable_days_ending_at_todays_balance():
    for a in ledger.ACCOUNT_IDS:
        h = ledger.history(a)
        assert len(h["dates"]) == 180 and h["dates"][-1] == "2026-10-28"
        assert h["balance"][-1] == ledger.account(a)["balance"] and min(h["balance"]) > 0
        assert ledger.history(a) == h


def test_bills_debit_on_their_day_with_the_last_three_cycles_from_the_bill_history():
    h = ledger.history(CARDS)
    aws = [(d, s["bill_aws"]) for d, s in zip(h["dates"], h["scheduled"]) if "bill_aws" in s]
    assert all(date.fromisoformat(d).day == 2 for d, _ in aws) and len(aws) == 6
    bill = next(b for b in RECURRING_BILLS if b["id"] == "bill_aws")
    assert [-v for _, v in aws[-3:]] == [sum(line["history"][i] for line in bill["lines"]) for i in range(3)]


def test_payroll_is_on_the_operating_account_and_top_ups_balance_out():
    ops, cards = ledger.history(OPS), ledger.history(CARDS)
    pay = [d for d, s in zip(ops["dates"], ops["scheduled"]) if "payroll" in s]
    assert {date.fromisoformat(d).day for d in pay} == {1, 15} and len(pay) == 11
    assert not any("payroll" in s for s in cards["scheduled"])
    out = [s["topup_cards"] for s in ops["scheduled"] if "topup_cards" in s]
    land = [s["topup_cards"] for s in cards["scheduled"] if "topup_cards" in s]
    assert out == [-v for v in land] and all(v > 0 for v in land)


def test_future_calendar_knows_the_schedule_and_the_thanksgiving_lull():
    cal = ledger.future_calendar(OPS)
    assert len(cal["dates"]) == 30 and cal["dates"][0] == "2026-10-29"
    pay = [d for d, v in zip(cal["dates"], cal["covariates"]["payroll_day"]) if v]
    lull = [d for d, v in zip(cal["dates"], cal["covariates"]["lull"]) if v]
    assert pay == ["2026-11-01", "2026-11-15"] and lull[0] == "2026-11-23" and lull[-1] == "2026-11-27"
    bills = [d for d, v in zip(ledger.future_calendar(MKT)["dates"], ledger.future_calendar(MKT)["covariates"]["bill_day"]) if v]
    assert bills == ["2026-11-01", "2026-11-03", "2026-11-04", "2026-11-06"]
    assert ledger.covariate_matrix(CARDS).shape == (len(ledger.COVARIATES), 210)


# ---------------------------------------------------------------- what Timestral gets

def test_timestral_gets_every_account_in_one_batch_with_known_covariates(monkeypatch):
    model = FakeTimestral()
    use_model(monkeypatch, model)
    raw = asyncio.run(horizon.run_forecast())
    assert len(model.calls) == 1
    call = model.calls[0]
    assert call["context"].shape == (3, 1, 180) and call["prediction_length"] == 30
    assert call["known"].shape == (3, len(ledger.COVARIATES), 210)
    assert list(call["context"][:, 0, -1]) == [240000.0, 135000.0, 70000.0]
    assert raw["source"] == "forecast model" and raw["notes"] == []
    assert raw["quantiles"][CARDS]["p50"] == [135000.0] * 30 and raw["quantiles"][MKT]["p10"][0] == 60000.0


def test_missing_timestral_uses_the_labelled_fallback(monkeypatch):
    no_model(monkeypatch)
    raw = asyncio.run(horizon.run_forecast())
    assert raw["source"] == "statistical fallback" and raw["route"] is None
    assert "Timestral unavailable" in raw["notes"][0] and "statistical fallback" in raw["notes"][0]


def test_slow_timestral_times_out_to_the_fallback(monkeypatch):
    use_model(monkeypatch, FakeTimestral(delay=0.5))
    monkeypatch.setattr(horizon, "settings", dataclasses.replace(horizon.settings, forecast_timeout_s=0.05))
    raw = asyncio.run(horizon.run_forecast())
    assert raw["source"] == "statistical fallback" and "longer than" in raw["notes"][0]


# ---------------------------------------------------------------- fallback, breach and sweep

def test_fallback_quantiles_are_ordered_and_widen():
    for a in ledger.ACCOUNT_IDS:
        q = horizon.statistical_forecast(a)
        assert all(len(q[k]) == 30 for k in ("p10", "p50", "p90"))
        assert all(x <= y <= z for x, y, z in zip(q["p10"], q["p50"], q["p90"]))
        widths = [z - x for x, z in zip(q["p10"], q["p90"])]
        assert all(w2 >= w1 - 0.05 for w1, w2 in zip(widths, widths[1:]))


def test_fallback_agrees_with_the_tactical_view_on_which_accounts_breach():
    raw = fallback_raw()
    ops, cards, mkt = (horizon.build(raw, a, {}) for a in (OPS, CARDS, MKT))
    assert ops["breach"] is None and ops["recommended_sweep"] is None
    assert cards["breach"]["date"] == "2026-11-03" and cards["breach"]["median_breach"] is False
    assert mkt["breach"]["date"] == "2026-11-06" and mkt["breach"]["median_breach"] is False
    s = cards["recommended_sweep"]
    assert s["amount"] == 15000 and s["date"] == "2026-11-02" and s["from"] == "Treasury money market (USD) ****9120"
    assert s["to"] == "Card settlement (USD) ****7731"
    assert [a["breach"] is not None for a in ops["accounts"]] == [False, True, True]


def test_executed_sweep_lifts_only_that_account_from_its_date():
    raw = fallback_raw()
    before = horizon.build(raw, CARDS, {})
    sweep = horizon.plan_sweep(raw, CARDS)
    after = horizon.build(raw, CARDS, {CARDS: sweep})
    assert after["breach"] is None and min(after["p10"]) >= after["floor"] and after["recommended_sweep"] is None
    i = after["dates"].index(sweep["date"])
    assert after["p50"][i - 1] == before["p50"][i - 1] and after["p50"][i] == before["p50"][i] + sweep["amount"]
    assert horizon.build(raw, MKT, {CARDS: sweep})["breach"] is not None


def test_no_sweep_when_the_corridor_clears_the_floor():
    q = {"p10": [80000.0] * 30, "p50": [90000.0] * 30, "p90": [100000.0] * 30}
    raw = {"quantiles": {a: q for a in ledger.ACCOUNT_IDS}, "source": "s", "model": "m", "route": None, "notes": []}
    f = horizon.build(raw, CARDS, {})
    assert f["breach"] is None and f["recommended_sweep"] is None


# ---------------------------------------------------------------- routes

@pytest.fixture
def client(monkeypatch):
    main.HORIZON.update(raw=None, sweeps={})
    return TestClient(main.app)


def test_forecast_returns_three_30_day_arrays_on_both_paths(client, monkeypatch):
    no_model(monkeypatch)
    a = client.get("/api/liquidity-guard/forecast?account_id=acct_cards").json()
    b = client.get("/api/liquidity/forecast?account_id=acct_cards").json()
    assert a == b and all(len(a[k]) == 30 for k in ("p10", "p50", "p90", "dates", "events"))
    assert a["floor"] == 60000 and a["source"] == "statistical fallback" and a["breach"]["date"] == "2026-11-03"
    assert client.get("/api/liquidity-guard/forecast").json()["account"]["id"] == OPS
    assert client.get("/api/liquidity-guard/forecast?account_id=nope").status_code == 404


def test_model_result_is_cached_but_a_fallback_is_not(client, monkeypatch):
    calls = []
    real = horizon.run_forecast

    async def counted():
        calls.append(1)
        return await real()

    monkeypatch.setattr(horizon, "run_forecast", counted)
    no_model(monkeypatch)
    client.get("/api/liquidity-guard/forecast")
    client.get("/api/liquidity-guard/forecast")
    assert len(calls) == 2
    use_model(monkeypatch, FakeTimestral())
    assert client.get("/api/liquidity-guard/forecast").json()["source"] == "forecast model"
    client.get("/api/liquidity-guard/forecast?account_id=acct_marketing")
    assert len(calls) == 3


def test_sweep_then_reset(client, monkeypatch):
    no_model(monkeypatch)
    f = client.post("/api/liquidity-guard/forecast/sweep?account_id=acct_marketing").json()
    assert f["executed_sweep"]["amount"] == 10000 and f["executed_sweep"]["simulated"] is True and f["breach"] is None
    assert client.post("/api/liquidity-guard/forecast/sweep?account_id=acct_marketing").status_code == 409
    cards = client.get("/api/liquidity-guard/forecast?account_id=acct_cards").json()
    assert cards["executed_sweep"] is None and [a["sweep"] is not None for a in cards["accounts"]] == [False, False, True]
    assert client.delete("/api/liquidity-guard/forecast").json()["cleared"]["sweeps"] == 1
    assert client.get("/api/liquidity-guard/forecast?account_id=acct_marketing").json()["executed_sweep"] is None


def test_sweep_is_refused_when_not_needed(client, monkeypatch):
    no_model(monkeypatch)
    assert client.post("/api/liquidity-guard/forecast/sweep?account_id=acct_operating").status_code == 409
