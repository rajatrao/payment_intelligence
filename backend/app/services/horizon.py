"""Liquidity Guard Strategic Horizon: a 30-day probabilistic cash forecast for the operating reserve.

The 180-day ledger and the 30-day calendar of known-future covariates (payroll days, month start and end, weekends,
lulls) go to Timestral, Mistral's time-series foundation model, which returns quantiles for every day ahead. The
10th, 50th and 90th percentiles (P10 pessimistic, P50 median, P90 optimistic) form an 80% corridor. If Timestral is
unavailable or slow, a seasonal statistical model computes the same three arrays from the ledger, and the response
says so; it never pretends to be the model.

From the corridor the engine finds the first day the P10 bound falls below the corporate floor, and sizes a
pre-emptive sweep from the treasury money market that keeps P10 above it. Executing the sweep is simulated: it is
recorded and added to the forecast, no money moves.
"""

import asyncio
import math
import threading
from datetime import date, timedelta

import numpy as np

from app.config import settings
from app.data.transactions.ledger import (COVARIATES, HISTORY_DAYS, HORIZON_ACCOUNT, HORIZON_DAYS, calendar_row,
                                          covariate_matrix, future_calendar, history)

Z90 = 1.2815515655446004   # standard normal 90th percentile: P10/P90 = P50 -/+ Z90 * sigma
SWEEP_STEP = 5000.0

_model = None
_state = {"status": "not loaded", "error": None}   # not loaded | loading | ready | unavailable
_lock = threading.Lock()


class ForecastUnavailable(Exception):
    pass


# ---------------------------------------------------------------- Timestral

def load_model():
    """Load Timestral once (the first run downloads the weights). Thread-safe; called at startup and on demand."""
    global _model
    if _model is not None:
        return _model
    if not _lock.acquire(blocking=False):
        raise ForecastUnavailable(f"{settings.forecast_model} is still loading (the first run downloads the weights)")
    try:
        if _model is None:
            _state["status"] = "loading"
            try:
                from timestral import TimestralForecaster  # optional dependency, see requirements-forecast.txt
            except ImportError as exc:
                _state.update(status="unavailable", error="the timestral package is not installed "
                                                          "(pip install -r requirements-forecast.txt)")
                raise ForecastUnavailable(_state["error"]) from exc
            try:
                _model = TimestralForecaster.from_pretrained(settings.forecast_model)
            except Exception as exc:  # weights not downloaded and no network, bad revision, …
                _state.update(status="unavailable", error=f"could not load {settings.forecast_model}: {exc}")
                raise ForecastUnavailable(_state["error"]) from exc
            _state.update(status="ready", error=None)
        return _model
    finally:
        _lock.release()


def model_status() -> dict:
    return {"model": settings.forecast_model, **_state}


def _timestral(balance: list[float]) -> dict:
    model = load_model()
    context = np.array(balance, dtype=float)[None, None, :]          # (series, variates, time)
    known = covariate_matrix()[None, :, :]                            # (series, covariates, time + horizon)
    out = model.forecast(context, prediction_length=HORIZON_DAYS, known_covariates=known)
    q = {p: np.asarray(out.quantile(p)).reshape(-1)[:HORIZON_DAYS] for p in (0.1, 0.5, 0.9)}
    return {k: [round(float(v), 2) for v in q[p]] for k, p in (("p10", 0.1), ("p50", 0.5), ("p90", 0.9))}


async def _model_forecast(balance: list[float]) -> dict:
    try:
        return await asyncio.wait_for(asyncio.to_thread(_timestral, balance), timeout=settings.forecast_timeout_s)
    except asyncio.TimeoutError as exc:
        raise ForecastUnavailable(f"Timestral took longer than {settings.forecast_timeout_s:.0f} s") from exc


# ---------------------------------------------------------------- statistical fallback

def _groups(hist: dict) -> dict:
    """Ordinary daily net flow by kind of day, and the scheduled amounts, learned from the ledger."""
    ordinary: dict[tuple, list[float]] = {}
    payroll, rent = [], []
    for d, flow in zip(hist["dates"], hist["net_flow"]):
        c = calendar_row(date.fromisoformat(d))
        if c["weekend"]:
            continue
        key = (c["month_end"], c["lull"])
        if not (c["payroll_day"] or c["month_start"]) and abs(flow) < 30000:
            ordinary.setdefault(key, []).append(flow)
    base = ordinary[(0, 0)]
    stats = {k: (float(np.mean(v)), float(np.std(v))) for k, v in ordinary.items() if len(v) >= 3}
    for d, flow in zip(hist["dates"], hist["net_flow"]):
        c = calendar_row(date.fromisoformat(d))
        if c["payroll_day"]:
            payroll.append(flow - stats[(0, 0)][0])
        elif c["month_start"] and not c["weekend"]:
            rent.append(flow - stats[(0, 0)][0])
        elif c["month_start"]:
            rent.append(flow)
    stats.setdefault((0, 0), (float(np.mean(base)), float(np.std(base))))
    return {"stats": stats, "payroll": float(np.mean(payroll)) if payroll else 0.0,
            "rent": float(np.mean(rent)) if rent else 0.0}


def statistical_forecast(hist: dict) -> dict:
    """Seasonal day-type model: expected daily flow and its variance, accumulated over the horizon."""
    g = _groups(hist)
    cal = future_calendar()["covariates"]
    level = hist["balance"][-1]
    mean, var, out = 0.0, 0.0, {"p10": [], "p50": [], "p90": []}
    for i in range(HORIZON_DAYS):
        c = {k: cal[k][i] for k in COVARIATES}
        if not c["weekend"]:
            m, s = g["stats"].get((c["month_end"], c["lull"]), g["stats"][(0, 0)])
            mean += m
            var += s * s
        if c["payroll_day"]:
            mean += g["payroll"]
        if c["month_start"]:
            mean += g["rent"]
        sd = math.sqrt(var)
        out["p50"].append(round(level + mean, 2))
        out["p10"].append(round(level + mean - Z90 * sd, 2))
        out["p90"].append(round(level + mean + Z90 * sd, 2))
    return out


# ---------------------------------------------------------------- corridor, breach and sweep

def _sweep_plan(q: dict, dates: list[str], floor: float) -> dict | None:
    low = min(q["p10"])
    if low >= floor:
        return None
    breach_i = next(i for i, v in enumerate(q["p10"]) if v < floor)
    # Cover the shortfall plus one step of headroom, in round steps.
    amount = math.ceil((floor - low) / SWEEP_STEP) * SWEEP_STEP + SWEEP_STEP
    # Land the transfer the business day before the breach (or tomorrow, if the breach is tomorrow).
    when = date.fromisoformat(dates[breach_i]) - timedelta(days=1)
    while when.weekday() >= 5:
        when -= timedelta(days=1)
    first = date.fromisoformat(dates[0])
    return {"amount": amount, "date": max(when, first).isoformat(), "from": HORIZON_ACCOUNT["sweep_source"],
            "to": HORIZON_ACCOUNT["name"], "covers_shortfall": round(floor - low, 2)}


def _apply(q: dict, dates: list[str], sweep: dict | None) -> dict:
    if not sweep:
        return q
    on = [d >= sweep["date"] for d in dates]
    return {k: [round(v + (sweep["amount"] if hit else 0.0), 2) for v, hit in zip(vals, on)] for k, vals in q.items()}


def _breach(q: dict, dates: list[str], floor: float) -> dict | None:
    i = next((i for i, v in enumerate(q["p10"]) if v < floor), None)
    if i is None:
        return None
    return {"day": i + 1, "date": dates[i], "p10": q["p10"][i], "p50": q["p50"][i],
            "median_breach": any(v < floor for v in q["p50"])}


async def run_forecast() -> dict:
    """Quantiles straight from the engine, before any sweep. The caller caches a model result, not a fallback."""
    hist = history()
    notes = []
    try:
        q = await _model_forecast(hist["balance"])
        source, model, route = "forecast model", settings.forecast_model, "timestral (local)"
    except ForecastUnavailable as exc:
        notes.append(f"Timestral unavailable: {exc}. Quantiles computed by the statistical fallback.")
        q = statistical_forecast(hist)
        source, model, route = "statistical fallback", "seasonal day-type model", None
    return {"quantiles": q, "source": source, "model": model, "route": route, "notes": notes}


def build(raw: dict, sweep: dict | None) -> dict:
    """The forecast response: history, the three quantile arrays (after any executed sweep), floor breach, sweep."""
    hist, cal = history(), future_calendar()
    floor = HORIZON_ACCOUNT["floor"]
    dates = cal["dates"]
    q = _apply(raw["quantiles"], dates, sweep)
    return {
        "account": HORIZON_ACCOUNT, "floor": floor, "horizon_days": HORIZON_DAYS, "history_days": HISTORY_DAYS,
        "history": {"dates": hist["dates"], "balance": hist["balance"]},
        "dates": dates, "p10": q["p10"], "p50": q["p50"], "p90": q["p90"],
        "covariates": cal["covariates"],
        "breach": _breach(q, dates, floor),
        "recommended_sweep": None if sweep else _sweep_plan(q, dates, floor),
        "executed_sweep": sweep,
        "source": raw["source"], "model": raw["model"], "route": raw["route"], "notes": raw["notes"],
    }


def plan_sweep(raw: dict) -> dict | None:
    return _sweep_plan(raw["quantiles"], future_calendar()["dates"], HORIZON_ACCOUNT["floor"])
