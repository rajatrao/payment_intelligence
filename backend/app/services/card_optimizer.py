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

# A decision model classifies; it doesn't do arithmetic. So the state carries the facts already worked out by
# corridor.py (which card works, what it saves, whether it removes the FX fee), and each option says exactly which
# facts it applies to.
REASON_CRITERIA = {
    "SCA_BYPASS_CORRIDOR": "sca_challenge is true: the payment was declined or held for 3-D Secure / SCA "
                           "authentication (code 1A or 65, or a 3DS challenge pending). Retry on a card with the "
                           "corporate SCA exemption in the merchant's region.",
    "INTER-REGIONAL_ROUTING": "regional_block is true (declined for a cross-region block, such as code 05), or there "
                              "is no SCA challenge, saving_meets_threshold is true and best_card_removes_fx_fee is "
                              "false: the saving comes from avoiding the cross-border fee with a card issued in the "
                              "merchant's region.",
    "FX_INTERBANK_MATCH": "No SCA challenge and no regional block, saving_meets_threshold is true and "
                          "best_card_removes_fx_fee is true: the best card holds the payment currency, so the FX "
                          "markup disappears.",
    NO_CHANGE: "No SCA challenge and no regional block, and saving_meets_threshold is false (or there is no "
               "working card). Never for a declined or pending payment that has a working card.",
}

REASON_QUESTION = "Which reason code matches these facts?"
CARD_QUESTION = ("Which company card should this payment be routed through? Pick the card marked best working "
                 "card. If there is none, pick the current card.")

SYSTEM_PROMPT = ("You are a corporate treasury payments engineer optimising card routing for cross-border payments. "
                 "Choose one reason code and one card.\n\nReason codes:\n"
                 + "\n".join(f"- {k}: {v}" for k, v in REASON_CRITERIA.items())
                 + "\n\nOnly recommend a card that can work. Never invent fees or cards.")

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


def _best(analysis: dict) -> dict | None:
    """Cheapest card that can clear the friction (the same pick the rule engine makes)."""
    working = sorted((o for o in analysis["options"] if o["eligible"]), key=lambda o: (o["fee_usd"], o["current"]))
    return working[0] if working else None


def _state(analysis: dict) -> dict:
    t, c, sig = analysis["transaction"], analysis["corridor"], analysis["signals"]
    current = next(o for o in analysis["options"] if o["current"])
    best = _best(analysis)
    saving = round(current["fee_usd"] - best["fee_usd"], 2) if best else 0.0
    payment = {k: t.get(k) for k in ("merchant", "amount", "currency", "status", "decline_code", "decline_text")}
    return {
        "payment": payment,
        "corridor": f"{c['issuer_country']} ({c['issuer_region']}) -> {c['merchant_country']} ({c['merchant_region']})",
        "facts": {
            "sca_challenge": sig["sca_challenge"],
            "regional_block": sig["regional_block"],
            "payment_failed": sig["failed"],
            "current_card": current["name"],
            "current_card_can_work": current["eligible"],
            "current_fee_usd": current["fee_usd"],
            "best_working_card": best["name"] if best else None,
            "best_card_fee_usd": best["fee_usd"] if best else None,
            "saving_usd": saving,
            "saving_meets_threshold": bool(best) and saving >= MIN_SAVING_USD,
            "best_card_removes_fx_fee": bool(best) and best["fx_bps"] == 0 and current["fx_bps"] > 0,
            "best_card_in_merchant_region": bool(best) and best["region"] == c["merchant_region"],
        },
    }


def _card_line(o: dict, best: dict | None) -> str:
    status = "can work" if o["eligible"] else "can't work: " + "; ".join(o["issues"])
    tags = "".join(t for t, on in ((" (current card)", o["current"]),
                                    (" (best working card)", best is not None and o["card_id"] == best["card_id"])) if on)
    return (f"{o['name']}{tags}, issued in {o['issuer_country']} ({o['region']}), "
            f"fee {o['fee_usd']:.2f} USD, {status}")


def _questions(analysis: dict) -> dict:
    return {
        "reason_code": {"type": "choice", "instructions": REASON_QUESTION, "criteria": REASON_CRITERIA},
        "card": {"type": "choice", "instructions": CARD_QUESTION,
                 "criteria": {o["card_id"]: _card_line(o, _best(analysis)) for o in analysis["options"]}},
    }


def _prompt(analysis: dict) -> str:
    cards = "\n".join(f"- {o['card_id']}: {_card_line(o, _best(analysis))}" for o in analysis["options"])
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

    raw = {"reason_code": out.get("reason_code"), "card_id": out.get("recommended_card_id")}
    agrees = raw["reason_code"] == rule["reason_code"] and (rule["reason_code"] == NO_CHANGE
                                                             or raw["card_id"] == rule["card_id"])
    warnings = []
    if out.get("reason_code") not in (*REASON_CODES, NO_CHANGE):
        warnings.append(f"model returned an unknown reason code {out.get('reason_code')!r}; showing the rule's")
        out = {**out, "reason_code": rule["reason_code"]}
    if out["reason_code"] == NO_CHANGE and rule["reason_code"] != NO_CHANGE:
        # NO_CHANGE contradicts the facts (a working card fixes a failed payment or saves above the threshold), so
        # it's a misread, not a judgement call: show the rule engine's answer and say so.
        facts = _state(analysis)["facts"]
        why = ("the payment failed and " + facts["best_working_card"] + " can clear it" if facts["payment_failed"]
               else f"{facts['best_working_card']} saves {facts['saving_usd']:.2f} USD")
        warnings.append(f"{model} chose NO_CHANGE, but {why}; showing the rule engine's answer")
        out = {**out, "reason_code": rule["reason_code"], "recommended_card_id": rule["card_id"]}
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
        "model_answer": raw,
        "agrees_with_rules": agrees,
        "warnings": warnings,
        **savings(analysis, card_id),
    }
