"""Card Optimizer: recommend how to route a cross-border payment, with a programmatic reason code.

corridor.py computes the facts (corridor, friction, each card's fees and eligibility). The decision is made by
Ollama's decision API (/v1/systemone, decision model nimble): two choice questions, one for the reason code and
one for the card, each answered with a probability per option. A decision model writes no text, so the action and
rationale are filled in from the facts. If the decision API is unavailable, gemma3 structured outputs make the
same choice; if neither is available, the rule engine's answer is used. The answer is always checked against the
deterministic rule, and savings always come from corridor.py, never from a model.
"""

import json

from app.config import settings
from app.data.transactions.cross_border import CARD_PORTFOLIO
from app.services.corridor import MIN_SAVING_USD, NO_CHANGE, REASON_CODES, savings
from app.services.ollama_client import OllamaUnavailable, decide, structured_chat

REASON_CRITERIA = {
    "SCA_BYPASS_CORRIDOR": "The payment hit a 3-D Secure / SCA challenge; route it through a card with the secure "
                           "corporate payment exemption in the merchant's region so no challenge is raised.",
    "FX_INTERBANK_MATCH": "The payment pays an FX markup; route it through a card that holds the payment currency "
                          "so it settles with no FX fee.",
    "INTER-REGIONAL_ROUTING": "The payment is blocked or charged a cross-border fee because issuer and merchant are "
                              "in different regions; route it through a card issued in the merchant's region.",
    NO_CHANGE: "No card is meaningfully better (saves less than 10 USD) or none can clear the friction.",
}

REASON_QUESTION = "Which routing action fixes this payment's friction at the lowest cost?"
CARD_QUESTION = ("Which company card should this payment be routed through? Only pick a card that can clear the "
                 "friction. If no card is better, pick the current card.")

SYSTEM_PROMPT = ("You are a corporate treasury payments engineer optimising card routing for cross-border payments. "
                 "Choose one reason code and one card.\n\nReason codes:\n"
                 + "\n".join(f"- {k}: {v}" for k, v in REASON_CRITERIA.items())
                 + "\n\nOnly recommend a card marked eligible. Never invent fees or cards.")

SCHEMA = {
    "type": "object",
    "properties": {
        "reason_code": {"type": "string", "enum": [*REASON_CODES, NO_CHANGE]},
        "recommended_card_id": {"type": "string", "enum": [c["id"] for c in CARD_PORTFOLIO]},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    },
    "required": ["reason_code", "recommended_card_id", "confidence"],
}

ACTIONS = {
    "SCA_BYPASS_CORRIDOR": "Retry on {card} under the secure corporate payment exemption.",
    "FX_INTERBANK_MATCH": "Pay {merchant} from {card}, which holds {currency}.",
    "INTER-REGIONAL_ROUTING": "Route {merchant} through {card}, issued in the merchant's region.",
    NO_CHANGE: "Keep the current card.",
}


def _state(analysis: dict) -> dict:
    t, c = analysis["transaction"], analysis["corridor"]
    payment = {k: t.get(k) for k in ("merchant", "mcc", "amount", "currency", "amount_usd", "status",
                                     "decline_code", "decline_text", "memo")}
    return {"payment": payment,
            "corridor": f"{c['issuer_country']} ({c['issuer_region']}) -> {c['merchant_country']} "
                        f"({c['merchant_region']}), inter-regional: {c['inter_regional']}",
            "friction": analysis["signals"], "current_fee_usd": analysis["current_fee_usd"]}


def _card_line(o: dict) -> str:
    status = "eligible" if o["eligible"] else "cannot clear the friction: " + "; ".join(o["issues"])
    return (f"{o['name']}{' (current card)' if o['current'] else ''}, issued in {o['issuer_country']} ({o['region']}), "
            f"fee {o['fee_usd']:.2f} USD ({o['total_bps']} bps), {status}")


def _questions(analysis: dict) -> dict:
    return {
        "reason_code": {"type": "choice", "instructions": REASON_QUESTION, "criteria": REASON_CRITERIA},
        "card": {"type": "choice", "instructions": CARD_QUESTION,
                 "criteria": {o["card_id"]: _card_line(o) for o in analysis["options"]}},
    }


def _prompt(analysis: dict) -> str:
    cards = "\n".join(f"- {o['card_id']}: {_card_line(o)}" for o in analysis["options"])
    return f"Payment:\n{json.dumps(_state(analysis), indent=1)}\n\nCards:\n{cards}"


def _explain(analysis: dict, reason_code: str, card_id: str | None) -> tuple[str, str]:
    """Action and rationale written from the facts, so every number shown comes from corridor.py."""
    t = analysis["transaction"]
    current = next(o for o in analysis["options"] if o["current"])
    card = next((o for o in analysis["options"] if o["card_id"] == card_id), None) or current
    if analysis["signals"]["failed"]:
        what = t["status"].replace("_", " ").capitalize() + (f" with code {t['decline_code']}" if t["decline_code"] else "")
        what += f" ({t['decline_text']})" if t["decline_text"] else ""
    else:
        fees = [f"{bps / 100:.2f}% {label}" for bps, label in ((current["fx_bps"], "FX"),
                                                                (current["cross_border_bps"], "cross-border")) if bps]
        what = f"Settled with {' and '.join(fees) or 'no'} fees ({current['fee_usd']:.2f} USD)"
    action = ACTIONS[reason_code].format(card=card["name"], merchant=t["merchant"], currency=t["currency"])
    if reason_code == NO_CHANGE:
        return action, f"{what}. No eligible card saves at least {MIN_SAVING_USD:.0f} USD on this payment."
    return action, (f"{what} on {current['name']}. {card['name']} is issued in {card['issuer_country']} "
                    f"({card['region']}) and costs {card['fee_usd']:.2f} USD here.")


async def _decide(analysis: dict) -> dict:
    answers = await decide(_state(analysis), _questions(analysis))
    reason, card = answers["reason_code"], answers["card"]
    return {"reason_code": reason.get("choice"), "recommended_card_id": card.get("choice"),
            "confidence": reason.get("confidence"), "probabilities": reason.get("probabilities") or {},
            "card_probabilities": card.get("probabilities") or {}}


async def recommend(analysis: dict) -> dict:
    rule = analysis["rule"]
    notes = []
    try:
        out = await _decide(analysis)
        source, model, route = "decision model", settings.decision_model, settings.nimble_path
    except OllamaUnavailable as exc:
        notes.append(f"Decision API unavailable: {exc}")
        try:
            out = await structured_chat(SYSTEM_PROMPT, _prompt(analysis), SCHEMA)
            source, model, route = "language model", settings.llm_model, "/api/chat"
        except OllamaUnavailable as exc2:
            notes.append(f"gemma3 unavailable: {exc2}")
            out = {"reason_code": rule["reason_code"], "recommended_card_id": rule["card_id"], "confidence": None}
            source, model, route = "rules (models unavailable)", "rules", None

    warnings = []
    if out.get("reason_code") not in (*REASON_CODES, NO_CHANGE):
        warnings.append(f"model returned an unknown reason code {out.get('reason_code')!r}; showing the rule's")
        out = {**out, "reason_code": rule["reason_code"]}
    option = next((o for o in analysis["options"] if o["card_id"] == out.get("recommended_card_id")), None)
    if out["reason_code"] != NO_CHANGE and (option is None or not option["eligible"]):
        warnings.append("model picked a card that can't clear this friction; showing the rule engine's card")
        out = {**out, "recommended_card_id": rule["card_id"]}
        option = next((o for o in analysis["options"] if o["card_id"] == rule["card_id"]), None)
    card_id = out.get("recommended_card_id") if out["reason_code"] != NO_CHANGE else None
    action, rationale = _explain(analysis, out["reason_code"], card_id)
    return {
        "transaction_id": analysis["transaction"]["id"],
        "reason_code": out["reason_code"],
        "recommended_card_id": out.get("recommended_card_id"),
        "recommended_card": option["name"] if option else None,
        "action": action,
        "rationale": rationale,
        "confidence": out.get("confidence"),
        "probabilities": out.get("probabilities") or {},
        "card_probabilities": out.get("card_probabilities") or {},
        "source": source, "model": model, "route": route, "notes": notes,
        "rule": rule,
        "agrees_with_rules": out["reason_code"] == rule["reason_code"]
        and (rule["reason_code"] == NO_CHANGE or out.get("recommended_card_id") == rule["card_id"]),
        "warnings": warnings,
        **savings(analysis, card_id),
    }
