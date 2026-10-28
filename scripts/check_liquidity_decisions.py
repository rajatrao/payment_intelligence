"""Run every Liquidity Guard bill through the running backend and compare the decision model with the rules.

Usage (with the app running, e.g. docker compose up):
    python3 scripts/check_liquidity_decisions.py [http://localhost:8000]

Clears earlier classifications, classifies each bill, prints one line per invoice line with nimble's probability
and the rule's answer, then the forecast it adds up to. The full responses go to scripts/liquidity_decisions.json,
so wording changes can be checked against the real decision model. Standard library only.
"""

import json
import sys
import urllib.request
from pathlib import Path

base = (sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000").rstrip("/")


def call(method: str, path: str) -> dict:
    req = urllib.request.Request(base + path, method=method)
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.loads(r.read())


call("DELETE", "/api/liquidity-guard/classifications")
bills = call("GET", "/api/liquidity-guard/bills")["forecast"]["bills"]
results, agree, total, forecast = [], 0, 0, None
for b in bills:
    body = call("POST", f"/api/liquidity-guard/bills/{b['id']}/classify")
    c, forecast = body["classification"], body["forecast"]
    results.append({"bill": b, "classification": c})
    print(f"{b['vendor']}  (debit {b['debit_date']}, via {c['model']} {c['route']})")
    for line in b["lines"]:
        r = c["lines"][line["id"]]
        p = "  -  " if r["probability"] is None else f"{r['probability']:.2f}"
        print(f"    {line['id']:17} {p}  model {'VARIABLE' if r['variable'] else 'FIXED':8}  "
              f"rules {'VARIABLE' if r['rule']['variable'] else 'FIXED':8}  {'OK' if r['agrees_with_rules'] else 'DIFF'}"
              f"  {line['description'][:60]}")
    for n in c.get("notes", []):
        print("    note:", n)
    agree += c["agreements"]
    total += len(c["lines"])

t = forecast["totals"]
print(f"\n{agree}/{total} lines agree with the rule engine.")
print(f"Auto-debits {t['debits']:,.2f} USD, variable exposure {t['variable_exposure']:,.2f}, "
      f"low point {t['low_point']['balance']:,.2f} on {t['low_point']['date']}, "
      f"buffer breach {t['first_breach'] or 'none'}.")
out = Path(__file__).with_name("liquidity_decisions.json")
out.write_text(json.dumps(results, indent=1))
print(f"Full responses: {out}")
