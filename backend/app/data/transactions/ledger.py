"""Daily ledger history and the forward calendar for the Liquidity Guard's Strategic Horizon forecast.

The same three bank accounts as the Tactical Ledger Guard (recurring.py), each with 180 days of end-of-day
balances up to the analysis date and a 30-day calendar of what is already known about the days ahead. Each
account's minimum buffer is its liquidity floor. The history is generated from a fixed seed, so every run sees the
same chaotic but repeatable ledger:

- the operating account takes customer receipts every business day (heavier at month end, lighter in a lull), pays
  ACH vendors, semi-monthly payroll on the 1st and 15th and its share of the recurring bills, and tops up the other
  two accounts,
- the card settlement account auto-pays the corporate card statement and the card-billed vendors early each month
  and is topped up from operating on the 20th,
- the marketing account pays the agency retainer and the ad platforms early each month and is topped up on the 25th,
- a late-summer lull (August) and a Thanksgiving lull, when receipts slow down.

The recurring bills debit on the same day of the month as in recurring.py, and their last three debits are the
three cycles of history listed there; earlier months continue the same trend backwards. The bills keep growing
faster than the top-ups, so each account drifts towards its floor and the forecast has a real question to answer.
"""

from datetime import date, timedelta

import numpy as np

from app.data.transactions.recurring import ACCOUNTS, ANALYSIS_DATE, RECURRING_BILLS

HISTORY_DAYS = 180
HORIZON_DAYS = 30
SEED = 7

SWEEP_SOURCE = "Treasury money market (USD) ****9120"
LULLS = [(date(2026, 8, 1), date(2026, 8, 31)), (date(2026, 11, 23), date(2026, 11, 27))]

# Known-future covariates sent with the history: the forecast may use them, never the amounts behind them.
COVARIATES = ["payroll_day", "bill_day", "funding_day", "weekend", "lull", "month_end"]

# Scheduled flows besides the recurring bills: (name, label, days of the month, kind, latest amount, monthly growth,
# month-to-month noise).
# Negative amounts leave the account. A top-up leaves operating and lands in the account it funds, the same day.
SCHEDULE = {
    "acct_operating": [
        ("payroll", "Payroll (semi-monthly)", (1, 15), "payroll", -98000.00, 0.010, 0.0),
        ("topup_cards", "Top-up to Card settlement ****7731", (20,), "funding", -68000.00, 0.0, 0.05),
        ("topup_marketing", "Top-up to Marketing ****4408", (25,), "funding", -44000.00, 0.0, 0.05),
    ],
    "acct_cards": [
        ("card_statement", "Corporate card statement (Visa)", (2,), "bill", -29000.00, 0.030, 0.12),
        ("topup_cards", "Top-up from Operating ****2210", (20,), "funding", 68000.00, 0.0, 0.05),
    ],
    "acct_marketing": [
        ("agency_retainer", "Agency retainer (Northpeak Media)", (1,), "bill", -16000.00, 0.0, 0.0),
        ("topup_marketing", "Top-up from Operating ****2210", (25,), "funding", 44000.00, 0.0, 0.05),
    ],
}

# Ordinary business-day flows: (receipts lognormal median, receipts sigma, outflow mean, outflow sd).
ORDINARY = {
    "acct_operating": (19500.0, 0.30, 4300.0, 900.0),
    "acct_cards": (0.0, 0.0, 120.0, 900.0),        # card fees and small refunds
    "acct_marketing": (0.0, 0.0, 220.0, 700.0),    # pay-as-you-go ad spend on the account's card
}


def _end() -> date:
    return date.fromisoformat(ANALYSIS_DATE)


def _is_lull(d: date) -> bool:
    return any(a <= d <= b for a, b in LULLS)


def _is_month_end(d: date) -> bool:
    return (d + timedelta(days=3)).month != d.month


def _months_before(d: date) -> int:
    """Whole months between d's month and the next debit month (November): October is 1, September 2, …"""
    end = _end()
    return (end.year - d.year) * 12 + end.month - d.month + 1


def _bill_events(account_id: str) -> list[tuple]:
    """The account's recurring bills as scheduled flows, with their last three debits taken from recurring.py."""
    out = []
    for b in RECURRING_BILLS:
        if b["account_id"] != account_id:
            continue
        cycles = [sum(line["history"][i] for line in b["lines"]) for i in range(3)]
        out.append((b["id"], b["vendor"], (date.fromisoformat(b["debit_date"]).day,), "bill", cycles))
    return out


def events(account_id: str) -> list[dict]:
    """Every scheduled flow on the account: name, label, days of the month and kind."""
    rows = [{"name": n, "label": lbl, "days": days, "kind": kind} for n, lbl, days, kind, *_ in SCHEDULE[account_id]]
    rows += [{"name": n, "label": lbl, "days": days, "kind": kind} for n, lbl, days, kind, _ in _bill_events(account_id)]
    return rows


def _due(account_id: str, d: date) -> list[dict]:
    return [e for e in events(account_id) if d.day in e["days"]]


def calendar_row(account_id: str, d: date) -> dict:
    kinds = {e["kind"] for e in _due(account_id, d)}
    return {"payroll_day": int("payroll" in kinds), "bill_day": int("bill" in kinds),
            "funding_day": int("funding" in kinds), "weekend": int(d.weekday() >= 5), "lull": int(_is_lull(d)),
            "month_end": int(_is_month_end(d) and d.weekday() < 5)}


def _history_days() -> list[date]:
    return [_end() - timedelta(days=HISTORY_DAYS - 1 - i) for i in range(HISTORY_DAYS)]


def _generate() -> dict:
    """All three ledgers from one seed, so a top-up out of operating is the same amount as the one landing."""
    rng = np.random.default_rng(SEED)
    days = _history_days()
    sched = {(aid, n): spec for aid, rows in SCHEDULE.items() for n, _, _, _, *spec in rows}
    noise = {}   # one draw per scheduled flow per month, shared by both sides of a top-up
    bills = {a["id"]: {n: cycles for n, *_, cycles in _bill_events(a["id"])} for a in ACCOUNTS}
    out = {}
    for a in ACCOUNTS:
        aid = a["id"]
        med, sigma, out_mean, out_sd = ORDINARY[aid]
        ordinary, scheduled = [], []
        for d in days:
            c = calendar_row(aid, d)
            flow = 0.0
            if not c["weekend"]:
                if med:
                    receipts = rng.lognormal(mean=np.log(med), sigma=sigma)
                    receipts *= 1.6 if c["month_end"] else 1.0
                    receipts *= 0.8 if c["lull"] else 1.0
                    flow += receipts
                flow -= rng.normal(out_mean, out_sd)
            ordinary.append(round(flow, 2))
            due = {}
            k = _months_before(d)
            for e in _due(aid, d):
                n = e["name"]
                if n in bills[aid]:
                    cycles = bills[aid][n]
                    if k <= 3:
                        amt = cycles[3 - k]
                    else:   # before the three listed cycles: the same month-on-month trend, backwards, with noise
                        ratio = (cycles[2] / cycles[0]) ** 0.5
                        key = (n, d.year, d.month)
                        noise.setdefault(key, rng.normal(1.0, 0.08))
                        amt = cycles[0] / ratio ** (k - 3) * noise[key]
                    due[n] = -round(amt, 2)
                else:
                    amount, growth, sd = sched[(aid, n)]
                    key = (n, d.year, d.month, d.day)
                    noise.setdefault(key, rng.normal(1.0, sd) if sd else 1.0)
                    due[n] = round(amount / (1 + growth) ** (k - 1) * noise[key], 2)
            scheduled.append(due)
        out[aid] = {"ordinary": ordinary, "scheduled": scheduled}
    return out


def history(account_id: str) -> dict:
    """180 days of end-of-day balances, oldest first, ending on the analysis date at the account's balance today."""
    acct = account(account_id)
    g = _generate()[account_id]
    flows = [round(o + sum(s.values()), 2) for o, s in zip(g["ordinary"], g["scheduled"])]
    closing = acct["balance"]
    # Anchor the last balance so the account ends the history where treasury sees it today.
    balances = list(np.round(closing - np.cumsum(flows[::-1])[::-1] + flows, 2))
    return {"dates": [d.isoformat() for d in _history_days()], "balance": [float(b) for b in balances],
            "net_flow": flows, "ordinary": g["ordinary"], "scheduled": g["scheduled"]}


def future_calendar(account_id: str) -> dict:
    days = [_end() + timedelta(days=i + 1) for i in range(HORIZON_DAYS)]
    rows = [calendar_row(account_id, d) for d in days]
    return {"dates": [d.isoformat() for d in days], "covariates": {k: [r[k] for r in rows] for k in COVARIATES},
            "events": [[e["label"] for e in _due(account_id, d)] for d in days]}


def covariate_matrix(account_id: str) -> np.ndarray:
    """Known covariates over history + horizon, shape (len(COVARIATES), HISTORY_DAYS + HORIZON_DAYS)."""
    days = [_end() - timedelta(days=HISTORY_DAYS - 1 - i) for i in range(HISTORY_DAYS + HORIZON_DAYS)]
    rows = [calendar_row(account_id, d) for d in days]
    return np.array([[r[k] for r in rows] for k in COVARIATES], dtype=float)


def account(account_id: str) -> dict:
    a = next(a for a in ACCOUNTS if a["id"] == account_id)
    return {"id": a["id"], "name": a["name"], "purpose": a["purpose"], "currency": a["currency"],
            "balance": float(a["balance"].replace(",", "")), "floor": a["minimum_buffer"],
            "sweep_source": SWEEP_SOURCE}


ACCOUNT_IDS = [a["id"] for a in ACCOUNTS]
