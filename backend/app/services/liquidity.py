"""Liquidity Guard forecast engine: deterministic numbers the decision model's classification drives.

Each bill line is either a variable usage-based consumption line or a fixed charge. That classification (made by
the decision model in liquidity_guard.py) decides how the line is forecast:

- variable: the month-to-date amount is only part of the cycle, so it is run-rated to the full cycle
  (mtd x cycle days / days elapsed);
- fixed: the amount is contracted, so the month-to-date amount is the charge.

The engine then lays every auto-debit and known cash flow on a timeline against the operating account and flags
where the balance falls below the minimum buffer. A keyword rule gives a second-opinion classification; it is
shown next to the model's answer, never used in its place.
"""

import re

from app.data.transactions.recurring import (ANALYSIS_DATE, CYCLE, KNOWN_FLOWS, OPERATING_ACCOUNT,
                                             RECURRING_BILLS)

# A variable line whose forecast is this much above its 3-cycle average is a surprise.
SPIKE_RATIO = 1.25

# Rule engine vocabulary. Strong usage markers win over fixed markers ("on-demand hosts above commitment").
_STRONG_USAGE = re.compile(r"on-demand|overage|above commitment|% of .*usage|per (1,000 )?(impression|click|request)"
                           r"|billed per|billed hourly", re.I)
_FIXED = re.compile(r"seat|licen[cs]e|user licenses|membership|commitment|committed|subscription|annual|"
                    r"savings plan|desks|/month|monthly fee", re.I)
_USAGE_UNITS = re.compile(r"\b(hrs|hours|tb|gb|tib|tokens|credits|segments|impressions|scanned|transfer|"
                          r"ingestion|pod hours|tib-months)\b", re.I)


def _amount(value) -> float:
    return round(float(str(value).replace(",", "").strip()), 2)


def rule_variable(line: dict) -> dict:
    """Keyword and history rule: the second opinion, and the fallback when no model is available."""
    text = line["description"]
    hist = line["history"]
    avg = sum(hist) / len(hist)
    spread = (max(hist) - min(hist)) / avg if avg else 0.0
    if _STRONG_USAGE.search(text):
        return {"variable": True, "why": "priced on metered usage"}
    if _FIXED.search(text):
        return {"variable": False, "why": "seat, licence or commitment pricing"}
    if _USAGE_UNITS.search(text):
        return {"variable": True, "why": "billed in usage units"}
    if spread > 0.10:
        return {"variable": True, "why": f"charges moved {spread:.0%} over the last 3 cycles"}
    return {"variable": False, "why": "flat charge over the last 3 cycles"}


def _line(raw: dict) -> dict:
    hist = [round(h, 2) for h in raw["history"]]
    return {"id": raw["id"], "description": raw["description"], "mtd": _amount(raw["mtd"]), "history": hist,
            "avg3": round(sum(hist) / len(hist), 2), "rule": rule_variable(raw)}


def bills() -> list[dict]:
    return [{**{k: b[k] for k in ("id", "vendor", "descriptor", "debit_date", "payment_method")},
             "lines": [_line(l) for l in b["lines"]]} for b in RECURRING_BILLS]


def get_bill(bill_id: str) -> dict | None:
    return next((b for b in bills() if b["id"] == bill_id), None)


def project(line: dict, variable: bool | None) -> float:
    """Forecast charge for the full cycle. Unclassified lines show only what is billed so far."""
    if variable:
        return round(line["mtd"] * CYCLE["days"] / CYCLE["days_elapsed"], 2)
    return line["mtd"]


def forecast(classifications: dict[str, bool]) -> dict:
    """Bills with per-line forecasts, the cash timeline and the totals, for the given line classifications."""
    out_bills, events = [], []
    for bill in bills():
        lines = []
        for line in bill["lines"]:
            variable = classifications.get(line["id"])
            projected = project(line, variable)
            lines.append({**line, "variable": variable, "projected": projected,
                          "change_pct": round((projected / line["avg3"] - 1) * 100, 1) if line["avg3"] else None,
                          "spike": bool(variable) and projected > line["avg3"] * SPIKE_RATIO})
        projected = round(sum(l["projected"] for l in lines), 2)
        avg3 = round(sum(l["avg3"] for l in lines), 2)
        classified = all(l["variable"] is not None for l in lines)
        out_bills.append({**bill, "lines": lines, "classified": classified, "projected": projected,
                          "billed_so_far": round(sum(l["mtd"] for l in lines), 2), "avg3": avg3,
                          "change_pct": round((projected / avg3 - 1) * 100, 1) if avg3 else None,
                          "variable_lines": sum(1 for l in lines if l["variable"]),
                          "spike": any(l["spike"] for l in lines)})
        events.append({"date": bill["debit_date"], "label": f"{bill['vendor']} auto-debit", "amount": -projected,
                       "kind": "bill", "bill_id": bill["id"], "estimate": not classified})
    events += [{**f, "kind": "flow", "bill_id": None, "estimate": False} for f in KNOWN_FLOWS]
    # Same-day outflows before inflows, so the low point is never understated.
    events.sort(key=lambda e: (e["date"], e["amount"] > 0, e["amount"]))

    balance = _amount(OPERATING_ACCOUNT["balance"])
    buffer = OPERATING_ACCOUNT["minimum_buffer"]
    low = {"balance": balance, "date": ANALYSIS_DATE}
    first_breach = None
    for e in events:
        balance = round(balance + e["amount"], 2)
        e["balance_after"] = balance
        e["below_buffer"] = balance < buffer
        if balance < low["balance"]:
            low = {"balance": balance, "date": e["date"]}
        if e["below_buffer"] and first_breach is None:
            first_breach = e["date"]

    variable_lines = [l for b in out_bills for l in b["lines"] if l["variable"]]
    debits = round(sum(b["projected"] for b in out_bills), 2)
    avg3_total = round(sum(b["avg3"] for b in out_bills), 2)
    return {
        "analysis_date": ANALYSIS_DATE, "cycle": CYCLE,
        "account": {**OPERATING_ACCOUNT, "balance": _amount(OPERATING_ACCOUNT["balance"])},
        "bills": out_bills, "timeline": events,
        "totals": {
            "debits": debits, "avg3": avg3_total,
            "change_pct": round((debits / avg3_total - 1) * 100, 1) if avg3_total else None,
            "variable_exposure": round(sum(l["projected"] for l in variable_lines), 2),
            "surprise": round(sum(l["projected"] - l["avg3"] for l in variable_lines), 2),
            "unclassified_bills": sum(1 for b in out_bills if not b["classified"]),
            "low_point": low, "first_breach": first_breach,
        },
    }
