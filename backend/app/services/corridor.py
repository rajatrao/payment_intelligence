"""Corridor analysis for the Card Optimizer: deterministic facts the model reasons over.

For each payment this works out the corridor (issuer country -> merchant country, and their regions), what kind of
friction it hit (SCA challenge, regional block, FX markup, cross-border fee), and what every card in the portfolio
would cost and whether it could succeed. The model (card_optimizer.py) picks the action and writes the reason;
the numbers it is shown, and the savings reported, always come from here.
"""

from app.data.transactions.cross_border import (ALPHA3, CARD_PORTFOLIO, CROSS_BORDER_TRANSACTIONS, FX_RATES_USD,
                                                REGIONS)

REASON_CODES = ["SCA_BYPASS_CORRIDOR", "FX_INTERBANK_MATCH", "INTER-REGIONAL_ROUTING"]
NO_CHANGE = "NO_CHANGE"

# Issuer response codes that mean "authenticate and retry" (Visa 1A, Mastercard 65) or a regional/MCC block.
SCA_DECLINE_CODES = {"1A", "65"}
BLOCK_DECLINE_CODES = {"05", "57", "62"}

CARDS = {c["id"]: c for c in CARD_PORTFOLIO}

# Re-routing a settled payment pattern is only worth recommending above this saving.
MIN_SAVING_USD = 10.0


def _country(code: str) -> str:
    code = (code or "").strip().upper()
    return ALPHA3.get(code, code)


def _amount(value) -> float:
    return round(float(str(value).replace(",", "").strip()), 2)


def normalise(raw: dict) -> dict:
    txn = {**raw, "merchant_country": _country(raw["merchant_country"]), "currency": raw["currency"].upper(),
           "amount": _amount(raw["amount"])}
    txn["amount_usd"] = round(txn["amount"] * FX_RATES_USD[txn["currency"]], 2)
    return txn


def card_cost(txn: dict, card: dict) -> dict:
    """Fees this card would incur on this payment, in basis points and USD."""
    fx_bps = 0 if txn["currency"] in card["currencies"] else card["fx_fee_bps"]
    inter_regional = REGIONS[card["issuer_country"]] != REGIONS[txn["merchant_country"]]
    xb_bps = card["cross_border_bps"] if inter_regional else 0
    return {"fx_bps": fx_bps, "cross_border_bps": xb_bps, "total_bps": fx_bps + xb_bps,
            "fee_usd": round(txn["amount_usd"] * (fx_bps + xb_bps) / 10_000, 2), "inter_regional": inter_regional}


def friction(txn: dict) -> dict:
    code = (txn.get("decline_code") or "").strip()
    text = (txn.get("decline_text") or "").lower()
    sca = code in SCA_DECLINE_CODES or "3ds" in text or "sca" in text or "authentication" in text
    block = code in BLOCK_DECLINE_CODES or "block" in text
    return {"sca_challenge": sca and not block, "regional_block": block, "failed": txn["status"] != "SETTLED"}


def card_options(txn: dict, signals: dict) -> list[dict]:
    """Every portfolio card with its cost and whether it can fix the friction."""
    merchant_region = REGIONS[txn["merchant_country"]]
    options = []
    for card in CARD_PORTFOLIO:
        cost = card_cost(txn, card)
        issues = []
        if card["id"] == txn["card_id"] and signals["failed"]:
            issues.append("this card already failed")
        if signals["sca_challenge"] and not (card["sca_exemption"] and REGIONS[card["issuer_country"]] == merchant_region):
            issues.append("would face the same SCA challenge")
        if signals["regional_block"] and cost["inter_regional"]:
            issues.append("still an inter-regional payment")
        options.append({"card_id": card["id"], "name": card["name"], "issuer_country": card["issuer_country"],
                        "region": REGIONS[card["issuer_country"]], "current": card["id"] == txn["card_id"],
                        **cost, "eligible": not issues, "issues": issues})
    return options


def analyse(raw: dict) -> dict:
    txn = normalise(raw)
    signals = friction(txn)
    options = card_options(txn, signals)
    current = next(o for o in options if o["current"])
    issuer = CARDS[txn["card_id"]]["issuer_country"]
    corridor = {"issuer_country": issuer, "merchant_country": txn["merchant_country"],
                "issuer_region": REGIONS[issuer], "merchant_region": REGIONS[txn["merchant_country"]],
                "cross_border": issuer != txn["merchant_country"], "inter_regional": current["inter_regional"]}
    tags = []
    if signals["sca_challenge"]:
        tags.append({"label": "SCA challenge", "tone": "red" if txn["status"] == "DECLINED" else "amber"})
    if signals["regional_block"]:
        tags.append({"label": "Regional block", "tone": "red"})
    if current["fx_bps"]:
        tags.append({"label": f"FX fee {current['fx_bps'] / 100:.2f}%", "tone": "amber"})
    if current["cross_border_bps"]:
        tags.append({"label": f"Cross-border {current['cross_border_bps'] / 100:.2f}%", "tone": "amber"})
    return {"transaction": txn, "corridor": corridor, "signals": signals, "tags": tags,
            "current_fee_usd": current["fee_usd"], "options": options, "rule": rule_recommendation(txn, signals, options)}


def rule_recommendation(txn: dict, signals: dict, options: list[dict]) -> dict:
    """The deterministic answer, used to check the model and as the fallback when it is unavailable."""
    current = next(o for o in options if o["current"])
    eligible = sorted((o for o in options if o["eligible"]), key=lambda o: (o["fee_usd"], o["current"]))
    if not eligible:
        return {"reason_code": NO_CHANGE, "card_id": None, "why": "no card in the portfolio clears this friction"}
    best = eligible[0]
    if signals["sca_challenge"]:
        code = "SCA_BYPASS_CORRIDOR"
    elif signals["regional_block"]:
        code = "INTER-REGIONAL_ROUTING"
    elif best["card_id"] == current["card_id"] or current["fee_usd"] - best["fee_usd"] < MIN_SAVING_USD:
        return {"reason_code": NO_CHANGE, "card_id": current["card_id"],
                "why": "no card saves at least {:.0f} USD on this payment".format(MIN_SAVING_USD)}
    elif best["fx_bps"] == 0 and current["fx_bps"] > 0:
        code = "FX_INTERBANK_MATCH"
    else:
        code = "INTER-REGIONAL_ROUTING"
    return {"reason_code": code, "card_id": best["card_id"], "why": f"cheapest eligible card ({best['fee_usd']:.2f} USD)"}


def savings(analysis: dict, card_id: str | None) -> dict:
    """Fees saved and payment volume recovered if the payment is re-routed to `card_id`."""
    if not card_id:
        return {"fees_saved_usd": 0.0, "recovered_usd": 0.0}
    option = next((o for o in analysis["options"] if o["card_id"] == card_id), None)
    txn = analysis["transaction"]
    if option is None:
        return {"fees_saved_usd": 0.0, "recovered_usd": 0.0}
    if analysis["signals"]["failed"]:
        # A failed payment hasn't cost fees yet; the saving is against retrying on the original card.
        return {"fees_saved_usd": round(max(0.0, analysis["current_fee_usd"] - option["fee_usd"]), 2),
                "recovered_usd": txn["amount_usd"] if option["eligible"] else 0.0}
    return {"fees_saved_usd": round(max(0.0, analysis["current_fee_usd"] - option["fee_usd"]), 2), "recovered_usd": 0.0}


def all_analyses() -> list[dict]:
    return [analyse(t) for t in CROSS_BORDER_TRANSACTIONS]


def get_analysis(txn_id: str) -> dict | None:
    raw = next((t for t in CROSS_BORDER_TRANSACTIONS if t["id"] == txn_id), None)
    return analyse(raw) if raw else None
