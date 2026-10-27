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
from app.services.corridor import CARDS, NO_CHANGE, REASON_CODES, savings
from app.services.ollama_client import OllamaUnavailable, decide, structured_chat

# The decision model gets the payment and the card portfolio as plain facts (decline code and text, corridor, what
# each card holds, its region, exemption and fees) and makes the judgement itself. Nothing tells it which card is
# right; the rule engine's answer is only shown next to it for comparison.
REASON_CRITERIA = {
    "SCA_BYPASS_CORRIDOR": "The cause is authentication: the payment was declined or is held because the issuer "
                           "demanded 3-D Secure / SCA (for example code 1A or 65, or a pending 3DS challenge). This "
                           "applies even when the card is also from another region. Fix: retry on a card with the "
                           "corporate SCA exemption issued in the merchant's region, so no challenge is raised.",
    "FX_INTERBANK_MATCH": "The cause is currency: the payment went through, but the current card doesn't hold the "
                          "payment currency, so it paid an FX markup. Use this whenever the current card's FX fee is "
                          "above 0%, even if it also paid a cross-border fee. Fix: pay from a card that holds that "
                          "currency.",
    "INTER-REGIONAL_ROUTING": "The cause is geography, not authentication: the payment was blocked as a "
                              "cross-region payment (for example code 05), or went through but paid a cross-border "
                              "fee because the card is from a different region than the merchant while the current "
                              "card's FX fee is 0% (it already holds the currency). Not for a 3-D Secure / SCA "
                              "decline. Fix: use a card issued in the merchant's region.",
    NO_CHANGE: "The payment went through and no other card would save a meaningful amount (about 10 USD or more).",
}

REASON_QUESTION = "What is the main cause of this payment's problem, judged from its status, decline reason and the current card's fees?"
CARD_QUESTION = ("Which company card should this payment be retried or paid on? Choose the card that fixes the "
                 "problem at the lowest fee. A card that already failed on this payment won't work.")

SYSTEM_PROMPT = ("You are a corporate treasury payments engineer optimising card routing for cross-border payments. "
                 "Choose one reason code and one card.\n\nReason codes:\n"
                 + "\n".join(f"- {k}: {v}" for k, v in REASON_CRITERIA.items())
                 + "\n\nNever invent fees or cards.")

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
    current = next(o for o in analysis["options"] if o["current"])
    payment = {k: t.get(k) for k in ("merchant", "mcc", "amount", "currency", "amount_usd", "status",
                                     "decline_code", "decline_text", "memo")}
    return {"payment": payment,
            "corridor": f"card issued in {c['issuer_country']} ({c['issuer_region']}), merchant in "
                        f"{c['merchant_country']} ({c['merchant_region']})",
            "current_card": current["name"],
            "current_card_fees": f"{current['fx_bps'] / 100:.2f}% FX + {current['cross_border_bps'] / 100:.2f}% "
                                 f"cross-border = {current['fee_usd']:.2f} USD"}


def _card_line(o: dict, analysis: dict) -> str:
    """Facts about one card on this payment. No verdict: the model decides whether it fits."""
    card, t, c = CARDS[o["card_id"]], analysis["transaction"], analysis["corridor"]
    current = next(x for x in analysis["options"] if x["current"])
    line = (f"{o['name']}{' (current card)' if o['current'] else ''}: issued in {o['issuer_country']} ({o['region']}"
            f"{', same region as the merchant' if o['region'] == c['merchant_region'] else ''}), holds "
            f"{'/'.join(card['currencies'])}, corporate SCA exemption: {'yes' if card['sca_exemption'] else 'no'}, "
            f"fees on this payment {o['fx_bps'] / 100:.2f}% FX + {o['cross_border_bps'] / 100:.2f}% cross-border = "
            f"{o['fee_usd']:.2f} USD")
    if not o["current"]:
        line += f", {current['fee_usd'] - o['fee_usd']:.2f} USD less than the current card"
    if o["current"] and analysis["signals"]["failed"]:
        line += f", already {t['status'].lower().replace('_', ' ')} on this payment"
    return line


def _questions(analysis: dict) -> dict:
    return {
        "reason_code": {"type": "choice", "instructions": REASON_QUESTION, "criteria": REASON_CRITERIA},
        "card": {"type": "choice", "instructions": CARD_QUESTION,
                 "criteria": {o["card_id"]: _card_line(o, analysis) for o in analysis["options"]}},
    }


def _prompt(analysis: dict) -> str:
    cards = "\n".join(f"- {o['card_id']}: {_card_line(o, analysis)}" for o in analysis["options"])
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
        return action, f"{what}. Judged not worth switching cards."
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

    # The model's answer is shown as given. The rule engine is a second opinion: disagreements and a card it
    # thinks can't clear the friction are flagged, never overwritten.
    agrees = out["reason_code"] == rule["reason_code"] and (rule["reason_code"] == NO_CHANGE
                                                             or out.get("recommended_card_id") == rule["card_id"])
    option = next((o for o in analysis["options"] if o["card_id"] == out.get("recommended_card_id")), None)
    warnings = []
    if out["reason_code"] != NO_CHANGE and option and not option["eligible"]:
        warnings.append(f"Rule engine: {option['name']} {'; '.join(option['issues'])}, so no payment is counted "
                        "as recovered")
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
        "agrees_with_rules": agrees,
        "warnings": warnings,
        **savings(analysis, card_id),
    }
