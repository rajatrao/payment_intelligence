"""Strategic Horizon: the ledger and calendar, what is sent to Timestral, the fallback, breach, sweep and routes."""

import asyncio
import dataclasses
import time
from datetime import date

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app import main
from app.data.transactions import ledger
from app.services import horizon


class FakeForecast:
    def __init__(self, q):
        self.q = q

    def quantile(self, p):
        return self.q[p]


class FakeTimestral:
    """Records the call and returns a straight-line corridor around the last balance."""

    def __init__(self, delay=0.0):
        self.calls, self.delay = [], delay

    def forecast(self, context, prediction_length, known_covariates):
        time.sleep(self.delay)
        self.calls.append({"context": context, "prediction_length": prediction_length, "known": known_covariates})
        base = context[0, 0, -1]
        q = {p: np.full((1, 1, prediction_length), base + off) for p, off in ((0.1, -10000), (0.5, 0), (0.9, 10000))}
        return FakeForecast(q)


def use_model(monkeypatch, model):
    monkeypatch.setattr(horizon, "load_model", lambda: model)


def no_model(monkeypatch, why="the timestral package is not installed"):
    def fail():
        raise horizon.ForecastUnavailable(why)
    monkeypatch.setattr(horizon, "load_model", fail)


# ---------------------------------------------------------------- ledger and calendar

def test_history_is_180_repeatable_days_ending_today():
    h = ledger.history()
    assert len(h["dates"]) == 180 and h["dates"][-1] == "2026-10-28" and h["balance"][-1] == 88000.0
    assert ledger.history() == h


def test_payroll_drops_every_other_friday():
    h = ledger.history()
    paydays = [d for d, f in zip(h["dates"], h["net_flow"]) if f < -40000 and date.fromisoformat(d).weekday() == 4]
    gaps = {(date.fromisoformat(b) - date.fromisoformat(a)).days for a, b in zip(paydays, paydays[1:])}
    assert len(paydays) >= 12 and gaps == {14}


def test_future_calendar_knows_payroll_and_the_thanksgiving_lull():
    cal = ledger.future_calendar()
    assert len(cal["dates"]) == 30 and cal["dates"][0] == "2026-10-29"
    pay = [d for d, v in zip(cal["dates"], cal["covariates"]["payroll_day"]) if v]
    lull = [d for d, v in zip(cal["dates"], cal["covariates"]["lull"]) if v]
    assert pay == ["2026-11-06", "2026-11-20"] and lull[0] == "2026-11-23" and lull[-1] == "2026-11-27"
    assert ledger.covariate_matrix().shape == (len(ledger.COVARIATES), 210)


# ---------------------------------------------------------------- what Timestral gets

def test_timestral_gets_the_history_and_known_covariates(monkeypatch):
    model = FakeTimestral()
    use_model(monkeypatch, model)
    raw = asyncio.run(horizon.run_forecast())
    call = model.calls[0]
    assert call["context"].shape == (1, 1, 180) and call["prediction_length"] == 30
    assert call["known"].shape == (1, len(ledger.COVARIATES), 210)
    assert call["context"][0, 0, -1] == 88000.0
    assert raw["source"] == "forecast model" and raw["notes"] == []
    assert raw["quantiles"]["p50"] == [88000.0] * 30 and raw["quantiles"]["p10"][0] == 78000.0


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
    q = horizon.statistical_forecast(ledger.history())
    assert all(len(q[k]) == 30 for k in ("p10", "p50", "p90"))
    assert all(a <= b <= c for a, b, c in zip(q["p10"], q["p50"], q["p90"]))
    widths = [c - a for a, c in zip(q["p10"], q["p90"])]
    assert all(w2 >= w1 - 0.05 for w1, w2 in zip(widths, widths[1:]))


def test_fallback_predicts_a_p10_breach_on_the_second_payroll():
    raw = {"quantiles": horizon.statistical_forecast(ledger.history()), "source": "statistical fallback",
           "model": "x", "route": None, "notes": []}
    f = horizon.build(raw, None)
    assert f["breach"]["day"] == 23 and f["breach"]["date"] == "2026-11-20" and f["breach"]["p10"] < 50000
    assert f["breach"]["median_breach"] is False
    s = f["recommended_sweep"]
    assert s["amount"] == 15000 and s["date"] == "2026-11-19" and s["from"] == "Treasury money market (USD) ****9120"


def test_executed_sweep_lifts_the_corridor_from_its_date():
    raw = {"quantiles": horizon.statistical_forecast(ledger.history()), "source": "s", "model": "m", "route": None,
           "notes": []}
    before = horizon.build(raw, None)
    sweep = horizon.plan_sweep(raw)
    after = horizon.build(raw, sweep)
    assert after["breach"] is None and min(after["p10"]) >= 50000 and after["recommended_sweep"] is None
    i = after["dates"].index(sweep["date"])
    assert after["p50"][i - 1] == before["p50"][i - 1] and after["p50"][i] == before["p50"][i] + 15000


def test_no_sweep_when_the_corridor_clears_the_floor():
    q = {"p10": [60000.0] * 30, "p50": [70000.0] * 30, "p90": [80000.0] * 30}
    f = horizon.build({"quantiles": q, "source": "s", "model": "m", "route": None, "notes": []}, None)
    assert f["breach"] is None and f["recommended_sweep"] is None


# ---------------------------------------------------------------- routes

@pytest.fixture
def client(monkeypatch):
    main.HORIZON.update(raw=None, sweep=None)
    return TestClient(main.app)


def test_forecast_returns_three_30_day_arrays_on_both_paths(client, monkeypatch):
    no_model(monkeypatch)
    a = client.get("/api/liquidity-guard/forecast").json()
    b = client.get("/api/liquidity/forecast").json()
    assert a == b and all(len(a[k]) == 30 for k in ("p10", "p50", "p90", "dates"))
    assert a["floor"] == 50000 and a["source"] == "statistical fallback" and a["breach"]["day"] == 23


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
    client.get("/api/liquidity-guard/forecast")
    assert len(calls) == 3


def test_sweep_then_reset(client, monkeypatch):
    no_model(monkeypatch)
    f = client.post("/api/liquidity-guard/forecast/sweep").json()
    assert f["executed_sweep"]["amount"] == 15000 and f["executed_sweep"]["simulated"] is True and f["breach"] is None
    assert client.get("/api/liquidity-guard/forecast").json()["executed_sweep"]["amount"] == 15000
    assert client.delete("/api/liquidity-guard/forecast").json()["cleared"]["sweep"] is True
    assert client.get("/api/liquidity-guard/forecast").json()["executed_sweep"] is None


def test_sweep_is_refused_when_not_needed(client, monkeypatch):
    model = FakeTimestral()
    use_model(monkeypatch, model)
    assert client.post("/api/liquidity-guard/forecast/sweep").status_code == 409
