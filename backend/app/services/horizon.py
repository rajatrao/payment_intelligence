"""Liquidity Guard Strategic Horizon: a 30-day probabilistic cash forecast for each bank account.

Each account's 180-day ledger and its 30-day calendar of known-future covariates (payroll, bill and top-up days,
weekends, lulls, month end) go to Timestral, Mistral's time-series foundation model, in one batch, which returns
quantiles for every day ahead. The 10th, 50th and 90th percentiles (P10 pessimistic, P50 median, P90 optimistic) form
an 80% corridor. If Timestral is unavailable or slow, a seasonal statistical model computes the same three arrays
from the ledger, and the response says so; it never pretends to be the model.

From the corridor the engine finds the first day the P10 bound falls below the account's floor (its minimum buffer)
and sizes a pre-emptive sweep from the treasury money market that keeps P10 above it. Executing the sweep is
simulated: it is recorded and added to the forecast, no money moves.
"""

import asyncio
import math
import threading
from datetime import date, timedelta

import numpy as np

from app.config import settings
from app.data.transactions.ledger import (ACCOUNT_IDS, COVARIATES, HISTORY_DAYS, HORIZON_DAYS, account,
                                          calendar_row, covariate_matrix, events, future_calendar, history)

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


def _timestral(balances: dict[str, list[float]]) -> dict:
    """One batched call: every account is a series, with its own known covariates."""
    model = load_model()
    ids = list(balances)
    context = np.array([balances[a] for a in ids], dtype=float)[:, None, :]   # (series, variates, time)
    known = np.stack([covariate_matrix(a) for a in ids])                      # (series, covariates, time + horizon)
    out = model.forecast(context, prediction_length=HORIZON_DAYS, known_covariates=known)
    q = {p: np.asarray(out.quantile(p)).reshape(len(ids), -1)[:, :HORIZON_DAYS] for p in (0.1, 0.5, 0.9)}
    return {a: {k: [round(float(v), 2) for v in q[p][i]] for k, p in (("p10", 0.1), ("p50", 0.5), ("p90", 0.9))}
            for i, a in enumerate(ids)}


async def _model_forecast(balances: dict[str, list[float]]) -> dict:
    try:
        return await asyncio.wait_for(asyncio.to_thread(_timestral, balances), timeout=settings.forecast_timeout_s)
    except asyncio.TimeoutError as exc:
        raise ForecastUnavailable(f"Timestral took longer than {settings.forecast_timeout_s:.0f} s") from exc


# ---------------------------------------------------------------- statistical fallback

def _ordinary_stats(hist: dict, account_id: str) -> dict:
    """Mean and spread of the unscheduled business-day flow, by kind of day (month end, lull)."""
    groups: dict[tuple, list[float]] = {}
    for d, flow in zip(hist["dates"], hist["ordinary"]):
        c = calendar_row(account_id, date.fromisoformat(d))
        if not c["weekend"]:
            groups.setdefault((c["month_end"], c["lull"]), []).append(flow)
    return {k: (float(np.mean(v)), float(np.std(v))) for k, v in groups.items() if len(v) >= 3}


def _scheduled_stats(hist: dict) -> dict:
    """For each scheduled flow, the next amount on its linear trend and the spread around that trend."""
    seen: dict[str, list[float]] = {}
    for due in hist["scheduled"]:
        for name, amount in due.items():
            seen.setdefault(name, []).append(amount)
    out = {}
    for name, amounts in seen.items():
        y = np.array(amounts)
        if len(y) >= 3:
            x = np.arange(len(y))
            slope, icpt = np.polyfit(x, y, 1)
            resid = y - (slope * x + icpt)
            nxt = slope * len(y) + icpt
            out[name] = (float(nxt), float(math.sqrt((resid ** 2).sum() / (len(y) - 2))), float(slope))
        else:
            out[name] = (float(y.mean()), float(y.std()), 0.0)
    return out


def statistical_forecast(account_id: str, hist: dict | None = None) -> dict:
    """Seasonal day-type model: expected daily flow and its variance, accumulated over the horizon."""
    hist = hist or history(account_id)
    ordinary = _ordinary_stats(hist, account_id)
    sched = _scheduled_stats(hist)
    cal = future_calendar(account_id)
    by_day = {e["name"]: e["days"] for e in events(account_id)}
    level = hist["balance"][-1]
    mean, var, seen, out = 0.0, 0.0, {}, {"p10": [], "p50": [], "p90": []}
    for i, d in enumerate(cal["dates"]):
        c = {k: cal["covariates"][k][i] for k in COVARIATES}
        if not c["weekend"]:
            m, s = ordinary.get((c["month_end"], c["lull"]), ordinary[(0, 0)])
            mean += m
            var += s * s
        for name, days in by_day.items():
            if date.fromisoformat(d).day in days and name in sched:
                nxt, s, slope = sched[name]
                mean += nxt + slope * seen.get(name, 0)
                var += s * s
                seen[name] = seen.get(name, 0) + 1
        sd = math.sqrt(var)
        out["p50"].append(round(level + mean, 2))
        out["p10"].append(round(level + mean - Z90 * sd, 2))
        out["p90"].append(round(level + mean + Z90 * sd, 2))
    return out


# ---------------------------------------------------------------- corridor, breach and sweep

def _sweep_plan(acct: dict, q: dict, dates: list[str]) -> dict | None:
    floor = acct["floor"]
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
    return {"account_id": acct["id"], "amount": amount, "date": max(when, first).isoformat(),
            "from": acct["sweep_source"], "to": acct["name"], "covers_shortfall": round(floor - low, 2)}


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
    """Quantiles for every account straight from the engine, before any sweep. The caller caches a model result."""
    hists = {a: history(a) for a in ACCOUNT_IDS}
    notes = []
    try:
        q = await _model_forecast({a: h["balance"] for a, h in hists.items()})
        source, model, route = "forecast model", settings.forecast_model, "timestral (local)"
    except ForecastUnavailable as exc:
        notes.append(f"Timestral unavailable: {exc}. Quantiles computed by the statistical fallback.")
        q = {a: statistical_forecast(a, h) for a, h in hists.items()}
        source, model, route = "statistical fallback", "seasonal day-type model", None
    return {"quantiles": q, "source": source, "model": model, "route": route, "notes": notes}


def _summary(raw: dict, account_id: str, sweep: dict | None) -> dict:
    acct, dates = account(account_id), future_calendar(account_id)["dates"]
    q = _apply(raw["quantiles"][account_id], dates, sweep)
    return {"id": acct["id"], "name": acct["name"], "balance": acct["balance"], "floor": acct["floor"],
            "p10_low": min(q["p10"]), "p50_end": q["p50"][-1], "p10": q["p10"], "p50": q["p50"], "p90": q["p90"],
            "breach": _breach(q, dates, acct["floor"]), "sweep": sweep}


def build(raw: dict, account_id: str, sweeps: dict) -> dict:
    """The forecast for one account (after any executed sweep), with a summary line for every account."""
    acct, hist, cal = account(account_id), history(account_id), future_calendar(account_id)
    sweep = sweeps.get(account_id)
    dates = cal["dates"]
    q = _apply(raw["quantiles"][account_id], dates, sweep)
    return {
        "account": acct, "floor": acct["floor"], "horizon_days": HORIZON_DAYS, "history_days": HISTORY_DAYS,
        "history": {"dates": hist["dates"], "balance": hist["balance"]},
        "dates": dates, "p10": q["p10"], "p50": q["p50"], "p90": q["p90"],
        "covariates": cal["covariates"], "events": cal["events"],
        "breach": _breach(q, dates, acct["floor"]),
        "recommended_sweep": None if sweep else _sweep_plan(acct, q, dates),
        "executed_sweep": sweep,
        "accounts": [_summary(raw, a, sweeps.get(a)) for a in ACCOUNT_IDS],
        "source": raw["source"], "model": raw["model"], "route": raw["route"], "notes": raw["notes"],
    }


def plan_sweep(raw: dict, account_id: str) -> dict | None:
    return _sweep_plan(account(account_id), raw["quantiles"][account_id], future_calendar(account_id)["dates"])
