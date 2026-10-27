"""Card Optimizer: recommend how to route a cross-border payment, with a programmatic reason code.

corridor.py computes the facts (corridor, friction, each card's fees and eligibility). gemma3 is asked, through the
structured-JSON route, to choose the action and explain it; its answer is constrained by a JSON schema to the
three reason codes and the portfolio's card ids. The answer is then checked against the deterministic rule, and
savings are always computed from corridor.py, never taken from the model.
"""

import json

from app.services.corridor import NO_CHANGE, REASON_CODES, savings
from app.services.ollama_client import OllamaUnavailable, structured_chat
from app.data.transactions.cross_border import CARD_PORTFOLIO

SYSTEM_PROMPT = """You are a corporate treasury payments engineer optimising card routing for cross-border
payments. You are given one payment, the friction it hit, and every company card with its fees and whether it can
clear that friction. Choose the single best card and action.

Reason codes (pick exactly one):
- SCA_BYPASS_CORRIDOR: the payment hit a 3-D Secure / SCA challenge; route it through a card that qualifies for
  the secure corporate payment exemption in the merchant's region so no challenge is raised.
- FX_INTERBANK_MATCH: the payment pays an FX markup; route it through a card that holds the payment currency so
  it settles at the interbank rate with no FX fee.
- INTER-REGIONAL_ROUTING: the payment is blocked or charged because issuer and merchant are in different regions;
  route it through a card issued in the merchant's region.
- NO_CHANGE: no card is meaningfully better.

Rules: only recommend a card marked eligible. Never invent fees or cards. The action is one imperative sentence.
The rationale is two sentences at most, citing the decline code, countries and fees given."""

SCHEMA = {
    "type": "object",
    "properties": {
        "reason_code": {"type": "string", "enum": [*REASON_CODES, NO_CHANGE]},
        "recommended_card_id": {"type": "string", "enum": [c["id"] for c in CARD_PORTFOLIO]},
        "action": {"type": "string"},
        "rationale": {"type": "string"},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    },
    "required": ["reason_code", "recommended_card_id", "action", "rationale", "confidence"],
}


def _prompt(analysis: dict) -> str:
    t, c = analysis["transaction"], analysis["corridor"]
    payment = {k: t.get(k) for k in ("merchant", "descriptor", "mcc", "amount", "currency", "amount_usd", "status",
                                     "decline_code", "decline_text", "memo")}
    cards = [{k: o[k] for k in ("card_id", "name", "issuer_country", "region", "current", "fx_bps",
                                "cross_border_bps", "fee_usd", "eligible", "issues")} for o in analysis["options"]]
    return (f"Payment:\n{json.dumps(payment, indent=1)}\n\nCorridor: {c['issuer_country']} ({c['issuer_region']}) -> "
            f"{c['merchant_country']} ({c['merchant_region']}); inter-regional: {c['inter_regional']}\n"
            f"Friction: {json.dumps(analysis['signals'])}\n\nCards:\n{json.dumps(cards, indent=1)}")


def _template(analysis: dict, rule: dict) -> dict:
    t = analysis["transaction"]
    card = next((o for o in analysis["options"] if o["card_id"] == rule["card_id"]), None)
    actions = {
        "SCA_BYPASS_CORRIDOR": "Retry on {card} under the secure corporate payment exemption.",
        "FX_INTERBANK_MATCH": "Pay {merchant} from {card}, which holds {currency}.",
        "INTER-REGIONAL_ROUTING": "Route {merchant} through {card}, issued in the merchant's region.",
        NO_CHANGE: "Keep the current card.",
    }
    name = card["name"] if card else "the current card"
    return {"reason_code": rule["reason_code"], "recommended_card_id": rule["card_id"],
            "action": actions[rule["reason_code"]].format(card=name, merchant=t["merchant"], currency=t["currency"]),
            "rationale": f"Rule engine: {rule['why']}.", "confidence": 1.0}


async def recommend(analysis: dict) -> dict:
    rule = analysis["rule"]
    try:
        out, model, route = await structured_chat(SYSTEM_PROMPT, _prompt(analysis), SCHEMA)
        source, error = "model", None
    except OllamaUnavailable as exc:
        out, model, route, source, error = _template(analysis, rule), "rules", None, "rules (model unavailable)", str(exc)

    option = next((o for o in analysis["options"] if o["card_id"] == out.get("recommended_card_id")), None)
    warnings = []
    if out.get("reason_code") not in (*REASON_CODES, NO_CHANGE):
        warnings.append(f"model returned an unknown reason code {out.get('reason_code')!r}")
    if out.get("reason_code") != NO_CHANGE and (option is None or not option["eligible"]):
        warnings.append("model picked a card that can't clear this friction; showing the rule engine's card")
        out = {**out, "recommended_card_id": rule["card_id"]}
        option = next((o for o in analysis["options"] if o["card_id"] == rule["card_id"]), None)
    card_id = out.get("recommended_card_id") if out.get("reason_code") != NO_CHANGE else None
    return {
        "transaction_id": analysis["transaction"]["id"],
        "reason_code": out.get("reason_code"),
        "recommended_card_id": out.get("recommended_card_id"),
        "recommended_card": option["name"] if option else None,
        "action": out.get("action"),
        "rationale": out.get("rationale"),
        "confidence": out.get("confidence"),
        "source": source, "model": model, "route": route, "error": error,
        "rule": rule,
        "agrees_with_rules": out.get("reason_code") == rule["reason_code"]
        and (rule["reason_code"] == NO_CHANGE or out.get("recommended_card_id") == rule["card_id"]),
        "warnings": warnings,
        **savings(analysis, card_id),
    }
