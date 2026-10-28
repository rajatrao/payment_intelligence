"""Run every Card Optimizer payment through the running backend and compare the decision model with the rules.

Usage (with the app running, e.g. docker compose up):
    python3 scripts/check_card_decisions.py [http://localhost:8000]

Prints one line per payment and writes the full responses to scripts/card_decisions.json, so prompt and
criteria changes can be checked against the real decision model. Standard library only.
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


payments = call("GET", "/api/card-optimizer/payments")["payments"]
results, agree = [], 0
for p in payments:
    t = p["transaction"]
    rec = call("POST", f"/api/card-optimizer/payments/{t['id']}/recommend")
    results.append({"payment": p, "recommendation": rec})
    agree += rec["agrees_with_rules"]
    top = ", ".join(f"{k} {v:.2f}" for k, v in sorted((rec.get("probabilities") or {}).items(), key=lambda kv: -kv[1]))
    print(f"{t['id']}  {t['merchant'][:22]:22}  {t['status']:12}  model {rec['reason_code']:22} "
          f"{rec['recommended_card_id'] or '':15}  rules {rec['rule']['reason_code']:22} {rec['rule']['card_id'] or '':15}"
          f"  {'OK' if rec['agrees_with_rules'] else 'DIFF'}  via {rec['model']} {rec['route']}\n    {top}")
    for n in rec.get("notes", []):
        print("    note:", n)

out = Path(__file__).with_name("card_decisions.json")
out.write_text(json.dumps(results, indent=1))
print(f"\n{agree}/{len(payments)} agree with the rule engine. Full responses: {out}")
