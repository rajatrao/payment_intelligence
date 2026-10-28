"""Run the Strategic Horizon forecast through the running backend and show which engine answered.

Usage (with the app running, e.g. docker compose up):
    python3 scripts/check_horizon.py [http://localhost:8000]

Clears any cached forecast and executed sweeps, asks for a fresh forecast, and prints whether Timestral or the
statistical fallback produced it and, for each account, the P10/P50/P90 corridor day by day, the floor breach and
the recommended sweep. The full responses go to scripts/horizon_forecast.json. Standard library only.
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


print("Timestral:", call("GET", "/api/health").get("forecast"))
call("DELETE", "/api/liquidity-guard/forecast")
first = call("GET", "/api/liquidity-guard/forecast")
print(f"Engine: {first['source']} ({first['model']}{', ' + first['route'] if first['route'] else ''})")
for n in first["notes"]:
    print("  note:", n)
full = {}
for a in first["accounts"]:
    f = call("GET", f"/api/liquidity-guard/forecast?account_id={a['id']}")
    full[a["id"]] = f
    print(f"\n{f['account']['name']}: today {f['account']['balance']:,.0f}, floor {f['floor']:,.0f}")
    print(f"{'day':>3}  {'date':10}  {'P10':>11}  {'P50':>11}  {'P90':>11}")
    for i, d in enumerate(f["dates"]):
        flag = "  < floor" if f["p10"][i] < f["floor"] else ""
        print(f"{i + 1:>3}  {d}  {f['p10'][i]:>11,.0f}  {f['p50'][i]:>11,.0f}  {f['p90'][i]:>11,.0f}{flag}")
    b, s = f["breach"], f["recommended_sweep"]
    print("  " + (f"P10 breach on day {b['day']} ({b['date']})" if b else "no P10 breach"))
    if s:
        print(f"  Recommended sweep: {s['amount']:,.0f} from {s['from']} on {s['date']}")
out = Path(__file__).with_name("horizon_forecast.json")
out.write_text(json.dumps(full, indent=1))
print(f"\nFull responses: {out}")
