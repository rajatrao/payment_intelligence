"""Daily ledger history and the forward calendar for the Liquidity Guard's Strategic Horizon forecast.

180 days of end-of-day balances for the operating reserve account, up to the analysis date, plus a 30-day calendar
of what is already known about the days ahead. The history is generated from a fixed seed, so every run sees the
same chaotic but repeatable ledger:

- bi-weekly payroll drops every other Friday,
- card settlement inflows from customers on business days, noisy and heavier at month end,
- ACH vendor outflows every business day, office rent on the 1st and a quarterly tax payment,
- a late-summer lull (August) and a Thanksgiving lull, when receipts slow down,
- one sweep in from the treasury money market ahead of the September tax payment.

The reserve drifts down over the six months, so the forecast has a real floor question to answer.
"""

from datetime import date, timedelta

import numpy as np

from app.data.transactions.recurring import ANALYSIS_DATE

HISTORY_DAYS = 180
HORIZON_DAYS = 30
SEED = 11

HORIZON_ACCOUNT = {
    "id": "acct_reserve",
    "name": "Operating reserve (USD) ****6604",
    "currency": "USD",
    "floor": 50000.00,
    "sweep_source": "Treasury money market (USD) ****9120",
}

PAYROLL = 61500.00          # every other Friday
FIRST_PAYROLL = date(2026, 5, 8)
RENT = 18400.00             # on the 1st
QUARTERLY_TAX = 42000.00    # 15 Jun and 15 Sep
PAST_SWEEPS = {date(2026, 9, 14): 60000.00}   # money market -> reserve
LULLS = [(date(2026, 8, 1), date(2026, 8, 31)), (date(2026, 11, 23), date(2026, 11, 27))]

# Known-future covariates sent with the history: the forecast may use them, never the amounts behind them.
COVARIATES = ["payroll_day", "month_start", "weekend", "lull", "month_end"]


def _end() -> date:
    return date.fromisoformat(ANALYSIS_DATE)


def _is_payroll(d: date) -> bool:
    return d >= FIRST_PAYROLL and (d - FIRST_PAYROLL).days % 14 == 0


def _is_lull(d: date) -> bool:
    return any(a <= d <= b for a, b in LULLS)


def _is_month_end(d: date) -> bool:
    return (d + timedelta(days=3)).month != d.month


def calendar_row(d: date) -> dict:
    return {"payroll_day": int(_is_payroll(d)), "month_start": int(d.day == 1), "weekend": int(d.weekday() >= 5),
            "lull": int(_is_lull(d)), "month_end": int(_is_month_end(d) and d.weekday() < 5)}


def history() -> dict:
    """180 days of end-of-day balances, oldest first, ending on the analysis date."""
    rng = np.random.default_rng(SEED)
    days = [_end() - timedelta(days=HISTORY_DAYS - 1 - i) for i in range(HISTORY_DAYS)]
    flows = []
    for d in days:
        c = calendar_row(d)
        net = 0.0
        if not c["weekend"]:
            receipts = rng.lognormal(mean=np.log(9800), sigma=0.3)
            receipts *= 1.6 if c["month_end"] else 1.0
            receipts *= 0.8 if c["lull"] else 1.0
            net += receipts - rng.normal(4300, 900)
        if c["payroll_day"]:
            net -= PAYROLL
        if c["month_start"]:
            net -= RENT
        if (d.month, d.day) in ((6, 15), (9, 15)):
            net -= QUARTERLY_TAX
        net += PAST_SWEEPS.get(d, 0.0)
        flows.append(round(net, 2))
    # Anchor the last balance so the account ends the history where treasury sees it today.
    closing = 88000.00
    balances = list(np.round(closing - np.cumsum(flows[::-1])[::-1] + flows, 2))
    return {"dates": [d.isoformat() for d in days], "balance": [float(b) for b in balances],
            "net_flow": flows}


def future_calendar() -> dict:
    days = [_end() + timedelta(days=i + 1) for i in range(HORIZON_DAYS)]
    rows = [calendar_row(d) for d in days]
    return {"dates": [d.isoformat() for d in days], "covariates": {k: [r[k] for r in rows] for k in COVARIATES}}


def covariate_matrix() -> np.ndarray:
    """Known covariates over history + horizon, shape (len(COVARIATES), HISTORY_DAYS + HORIZON_DAYS)."""
    days = [_end() - timedelta(days=HISTORY_DAYS - 1 - i) for i in range(HISTORY_DAYS + HORIZON_DAYS)]
    rows = [calendar_row(d) for d in days]
    return np.array([[r[k] for r in rows] for k in COVARIATES], dtype=float)
